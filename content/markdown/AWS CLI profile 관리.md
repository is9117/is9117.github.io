Title: AWS CLI profile 관리
Date: 2024-01-15 16:36
Modified: 2024-01-18 09:12
Category: infra
Tags: aws, infra
Author: Isaac Park
Summary: AWS CLI profile



## Abstract

local aws cli에서 여러 계정을 switch해야 되는 경우가 있습니다. 예로 dev, stage, prod환경을 대상으로 aws cli를 사용해야 되는 경우가 있습니다.

이런 상황에서 env파일로만 아니라, shell에서 바로 계정을 switch하는 방법을 기록하려고 합니다.

## AWS 설정파일

여기서 소개할 파일 외 여러 설정파일이 있지만, 가장 기본적인 설정파일에 대한 설명을 하려고 합니다.

두 파일 다 `aws configure` 명령어로 자동 생성되는 파일입니다.

`~/.aws/config`

```bash
[default]
region = ap-northeast-2

[profile jessie]
region = ap-northeast-2

[profile isaac]
region = ap-northeast-2
```

region, format 등 설정파일을 저장하는 장소입니다.

`[profile {profile_name}]` 포멧으로 프로파일을 구분할 수 있습니다.

`~/.aws/credentials`

```bash
[default]
aws_access_key_id = AK....EW
aws_secret_access_key = XM....HY

[jessie]
aws_access_key_id = AK....EW
aws_secret_access_key = XM....HY

[isaac]
aws_access_key_id = AK....HF
aws_secret_access_key = Zs....uS
```

access key, access secret key 등 credential정보 저장소 입니다.

`[{profile_name}]` 포멧으로 프로파일을 구분하고 있습니다.

## AWS 환경변수

aws cli가 사용되는 환경변수 중 profile switching에 연관 된 내용만 설명합니다.

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

`AWS_PROFILE`

위에서 아래로 우선순위를 가집니다. 즉 명령어 option으로 override하지 않는 이상 위에 환경변수가 우선순위를 가지고 실행됩니다.

`AWS_PROFILE`은 config, credentials 파일의 프로파일명을 사용하는 환경변수입니다.

## Profile switching

### 환경변수

```bash
export AWS_PROFILE=jessie
aws sts get-caller-identity
{
    "UserId": "AIDAVGIMKKMMBD5INZV4W",
    "Account": "357044998936",
    "Arn": "arn:aws:iam::357044998936:user/jesse@huinno.com"
}
```

주의 해야 할 부분은 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` 환경변수가 설정 되어있을 경우에는 override되어 AWS_PROFILE을 무시하고 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`기준으로 aws api호출하게 됩니다.

### Option

```bash
export AWS_PROFILE=default   # 이 부분 무시 됨
aws sts get-caller-identity --profile isaac   # override
{
    "UserId": "AIDAVGIMKKMMDYH5AHYDB",
    "Account": "357044998936",
    "Arn": "arn:aws:iam::357044998936:user/isaac.park@huinno.com"
}
```

`—-profile` 옵션으로 환경변수 설정을 override할 수 있습니다.

## Profile 추가

### AWS CLI사용

```bash
aws configure --profile {new_profile_name}
AWS Access Key ID [None]: ....
AWS Secret Access Key [None]: ....
Default region name [None]: ap-norteast-2
Default output format [None]:
```

### 설정 파일 수정

`~/.aws/config`

```bash
[default]
region = ap-northeast-2

[profile jessie]
region = ap-northeast-2

[profile isaac]
region = ap-northeast-2

[profile {new_profile_name}]
region = ap-notrheast-2
```

`~/.aws/credentials`

```bash
[default]
aws_access_key_id = AK....EW
aws_secret_access_key = XM....HY

[jessie]
aws_access_key_id = AK....EW
aws_secret_access_key = XM....HY

[isaac]
aws_access_key_id = AK....HF
aws_secret_access_key = Zs....uS

[{new_profile_name}]
aws_access_key_id = AK....HF
aws_secret_access_key = Zs....uS
```