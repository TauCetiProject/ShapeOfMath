#!/usr/bin/env bash
# Run one quarterly OpenAlex mathematics release on a self-terminating EC2 instance.
#
#   ./openalex_math_ec2.sh setup     # idempotent: bucket, IAM role/instance profile
#   ./openalex_math_ec2.sh launch    # upload code, start the instance, print the run id
#   ./openalex_math_ec2.sh status RUN
#
# Environment: AWS_PROFILE (default openalex), BUCKET, INSTANCE_TYPE, VOLUME_GB.
# See docs/OPENALEX_MATH.md.
set -euo pipefail
export AWS_PROFILE=${AWS_PROFILE:-openalex} AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=${BUCKET:-openalex-math-$ACCOUNT}
ROLE=openalex-math-ec2
INSTANCE_TYPE=${INSTANCE_TYPE:-r7i.xlarge}
VOLUME_GB=${VOLUME_GB:-100}
HERE=$(cd "$(dirname "$0")" && pwd)

setup() {
  if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    aws s3api create-bucket --bucket "$BUCKET" >/dev/null
    echo "created s3://$BUCKET"
  fi
  if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
    aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
      '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
    echo "created role $ROLE"
  fi
  aws iam put-role-policy --role-name "$ROLE" --policy-name bucket --policy-document "$(cat <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":"arn:aws:s3:::$BUCKET"},
 {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::$BUCKET/*"}]}
EOF
)"
  if ! aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
    aws iam create-instance-profile --instance-profile-name "$ROLE" >/dev/null
    aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
    echo "created instance profile $ROLE (allow ~10s to propagate before launch)"
  fi
  echo "bucket s3://$BUCKET, role $ROLE ready"
}

launch() {
  RUN=$(date -u +%Y%m%dT%H%M%SZ)
  aws s3 cp --only-show-errors "$HERE/openalex_math.py" "s3://$BUCKET/runs/$RUN/openalex_math.py"
  AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
        --query Parameter.Value --output text)
  USERDATA=$(sed -e "s|__BUCKET__|$BUCKET|g" -e "s|__RUN__|$RUN|g" <<'EOF'
#!/bin/bash
set -euo pipefail
B=__BUCKET__; RUN=__RUN__; LOG=/var/log/openalex-math.log
exec > >(tee -a $LOG) 2>&1
shutdown -h +720   # hard stop after 12 hours whatever happens
finish() {
  status=$?
  echo "exit status $status"
  aws s3 cp --only-show-errors $LOG s3://$B/runs/$RUN/log.txt || true
  echo $status | aws s3 cp --only-show-errors - s3://$B/runs/$RUN/status || true
  shutdown -h now
}
trap finish EXIT
export HOME=/root
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH=$HOME/.local/bin:$PATH
mkdir -p /work/out && cd /work
aws s3 cp --only-show-errors s3://$B/runs/$RUN/openalex_math.py .
aws s3 sync --only-show-errors s3://$B/data /work/out/data
aws s3 cp --only-show-errors s3://$B/state.json /work/out/state.json || echo "no previous release"
( while sleep 300; do aws s3 cp --only-show-errors $LOG s3://$B/runs/$RUN/log.txt || true; done ) &
uv run -q --python 3.12 --with pyarrow==26.0.1 --with numpy==2.5.4 python openalex_math.py release \
  --upstream s3://openalex/data/parquet --out /work/out --publish-url s3://$B/data/parquet --workers 4
# Publish like upstream: manifests are removed first and written last (present = complete).
aws s3 rm --only-show-errors --recursive s3://$B/data --exclude '*' --include '*manifest.json'
aws s3 sync --only-show-errors --delete /work/out/data s3://$B/data --exclude '*manifest.json'
aws s3 cp --only-show-errors /work/out/state.json s3://$B/state.json
aws s3 cp --only-show-errors /work/out/data/parquet/works/manifest.json s3://$B/data/parquet/works/manifest.json
aws s3 cp --only-show-errors /work/out/data/parquet/citations/manifest.json s3://$B/data/parquet/citations/manifest.json
aws s3 cp --only-show-errors /work/out/data/parquet/manifest.json s3://$B/data/parquet/manifest.json
aws s3 cp --only-show-errors s3://openalex/LICENSE.txt s3://$B/UPSTREAM_LICENSE.txt
echo "published"
EOF
)
  ID=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
       --iam-instance-profile Name=$ROLE --instance-initiated-shutdown-behavior terminate \
       --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=$VOLUME_GB,VolumeType=gp3,Throughput=500,DeleteOnTermination=true}" \
       --metadata-options HttpTokens=required \
       --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=openalex-math-$RUN}]" \
       --user-data "$USERDATA" --query 'Instances[0].InstanceId' --output text)
  echo "run $RUN instance $ID"
}

status() {
  RUN=$1
  aws ec2 describe-instances --filters "Name=tag:Name,Values=openalex-math-$RUN" \
    --query 'Reservations[].Instances[].[InstanceId,State.Name,LaunchTime]' --output text
  aws s3 cp --only-show-errors "s3://$BUCKET/runs/$RUN/status" - 2>/dev/null | sed 's/^/exit status: /' || echo "running (no status yet)"
  aws s3 cp --only-show-errors "s3://$BUCKET/runs/$RUN/log.txt" - 2>/dev/null | tail -20 || true
}

case "${1:-}" in
  setup) setup ;;
  launch) launch ;;
  status) status "${2:?run id}" ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
