param(
  [string]$Region = "ap-south-1",
  [string]$StackName = "carecircle-automation",
  [string]$OutreachMode = "simulation",
  [string]$SesFromEmail = "anshulnautiyal2006@gmail.com",
  [string]$Bucket = "carecircle-extractions-615664941000-ap-south-1"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$packaged = Join-Path $root "packaged-template.yaml"

& (Join-Path $PSScriptRoot "package.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$authSecret = aws lambda get-function-configuration `
  --function-name CareCircleAuthApi `
  --region $Region `
  --query "Environment.Variables.AUTH_SECRET" `
  --output text
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

aws cloudformation package `
  --template-file (Join-Path $root "template.yaml") `
  --s3-bucket $Bucket `
  --s3-prefix "carecircle-automation" `
  --output-template-file $packaged `
  --region $Region
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

aws cloudformation deploy `
  --template-file $packaged `
  --stack-name $StackName `
  --capabilities CAPABILITY_NAMED_IAM `
  --region $Region `
  --parameter-overrides `
    AuthSecret=$authSecret `
    SesFromEmail=$SesFromEmail `
    OutreachMode=$OutreachMode
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

aws cloudformation describe-stacks `
  --stack-name $StackName `
  --region $Region `
  --query "Stacks[0].Outputs" `
  --output table
