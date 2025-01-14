Title: Feature toggle(or flag)
Date: 2024-03-22 11:38
Modified: 2024-03-22 11:38
Tags: backend, deploy, git, operation
Author: 박이삭
Category: backend
Summary: feature flag

---

## ⛰️ 배경

여러 명이 대규모 git 저장소에서 동시에 개발을 진행하며 겪게 되는 여러 가지 이슈들에 대해 알아보겠습니다. 더 나아가 이런 이슈들에 대해 소개해 드리려고 합니다.
여기서는 dev / release / main branch를 각각 Dev / QA / Prod환경에 매칭하여 배포 및 운영을 하는 조직에게 소개드리는 가정을 하고있습니다.

## ⚠️ 이슈

많은 개발조직에서 여러 feature branch를 관리하며 QA 환경에 배포하는 과정에서 종종 예상치 못한 어려움을 마주하게 됩니다. QA 환경에서 외부 요인으로 인해 특정 기능의 배포 일정이 지연될 경우, 다른 스쿼드에서 배포를 진행해야 하는 상황이 발생할 수 있습니다. 이때 이미 release branch에 머지된 코드를 되돌리거나, 배포에 영향을 주지 않기 위해 임시로 코드를 주석 처리 후 커밋하는 등의 작업이 필요할 수 있습니다. 이러한 과정은 추가적인 시간과 노력을 요구하며 배포 프로세스를 복잡하게 만듭니다.

또 다른 문제로는 각 스쿼드의 개발 주기와 기간이 다르기 때문에, 개발이 완전히 완료되지 않은 코드를 최신 branch에 바로 머지할 수 없는 상황이 생길 수 있습니다. 이렇게 되면 최신 branch와의 동기화가 지연되어, 최종적으로 머지할 때 코드 충돌이나 데이터베이스 마이그레이션 충돌과 같은 복잡한 문제가 발생할 가능성이 높아집니다.

이러한 문제를 해결하기 위해 Feature Toggle을 활용하면 효과적입니다. Feature Toggle은 개발 중인 기능을 작은 단위로 나누어 관리할 수 있도록 도와주는 기술입니다. 이를 통해 아래와 같은 이점을 얻을 수 있습니다.

짧은 단위의 PR 작성
기능을 작은 단위로 분리하면, PR을 작성하기 전에 필요한 단위 테스트 코드를 명확히 정의할 수 있습니다. 또한 리뷰해야 할 코드 범위가 줄어들어 리뷰어의 부담도 줄어듭니다.

코드 동기화 주기 단축
최신 branch와의 동기화를 더 자주 할 수 있어 코드 충돌이나 마이그레이션 충돌을 줄이는 데 도움이 됩니다.

배포 프로세스 간소화
QA 환경에서 특정 기능 배포가 지연되더라도 다른 스쿼드의 배포에 영향을 주지 않도록 관리할 수 있습니다.

Feature Toggle은 특히 여러 팀이 병렬로 개발을 진행하거나 복잡한 배포 프로세스를 효율적으로 관리해야 하는 환경에서 필수적인 도구로 자리 잡고 있습니다. 이를 적극적으로 활용하면 개발 효율성을 높이고 배포 과정에서의 스트레스를 크게 줄일 수 있을 것입니다.



![Untitled](../images/feature_flags/Untitled.png)

## 🚦 Feature toggle

### 1. 기능설명

feature toggle을 통해 이러한 문제를 해결할 수 있습니다.

feature toggle이란 신규 개발 되는 기능과 이전 기능을 toggle(혹은 flag)로 선택할 수 있게 하는 기술입니다. toggle은 여러 방식으로 구현이 가능합니다.

**저장소**

- 환경변수
- DB
- cache

저장소들은 각자의 장단점이 있습니다. DB나 cache저장소 사용 시 라이브로 기능을 on, off 할 수 있습니다. 다만 추가 network를 타야하는(DB경우 별도 overhead) overhead가 있습니다. 환경변수 사용 시 서버 실행 시 초기 설정으로 overhead가 (branch miss overhead 외)  거의없는 장점이 있지만, toggle on, off 시 서버 재배포가 필요합니다.

![Untitled](../images/feature_flags/Untitled%201.png)

feature toggle은 이런 이슈해결 뿐만이 아니라 여러 추가 기능이 있습니다.

- 유연한 배포 일정: 기능 릴리즈 일정까지 기다리지 않고 미리 배포 및 테스트 가능
- git 통합 cycle 축소: 큰 기능을 작은 규모의 기능으로 쪼개어 개발 및 통합
- 서비스 dependency 제한X: 연동되는 파트(web, mobile, win32, etc.)나 서비스의 호환이 될때 까지 신규 기능 배포 대기 불필요
- 사용자 별 기능 배포(permission toggle): 특정 사용자에게만 선별하여 기능을 배포하고 테스트 후 전체 적용하는 기능이 있습니다. toggle router 등 기능 필요
- canary 배포(canary toggle): 기능 동작을 비율적으로 배포하여(예. 20% : 80%) Prod에서 서비스 동작을 점진적으로 테스트 할 수 있습니다. DB 저장소 및 복잡한 router 필요
- A/B 테스트: 같은 기능이지만 다른 알고리즘을 구현 한 경우 특정 조건을 기준으로 다른 두(혹은 둘 이상) 알고리즘을 같이 서비스 할 수 있습니다. 사용자 별 혹은 랜덤으로 두 알고리즘을 돌려 서로 A/B 테스트를 진행 할 수 있습니다.

### 2. toggle category

toggle아래 이미지 처럼 여러 종류로 분류하고, life cycle을 관리 할 수 있습니다.

![참고: [https://martinfowler.com/articles/feature-toggles.html](https://martinfowler.com/articles/feature-toggles.html)](../images/feature_flags/Untitled%202.png)

참고: [https://martinfowler.com/articles/feature-toggles.html](https://martinfowler.com/articles/feature-toggles.html)

**Release toggles:**

기능배포와 코드배포를 분리 할 수 있는 릴리즈 관련 toggle

**Experiment toggle:**

실서비스에서 시험(A/B 테스트, 신기능 등)을 하고 싶을 때 사용할 수 있습니다.

**Ops toggle:**

개발자 권한으로 무엇인가를 하고 싶거나 운영 측면 제어를 위해 사용됩니다. 예로 B2C서비스에서 부하가 많은 추천알고리즘이 서비스 트레픽이 갑자기 spike할 시 disable할 수 있는 “Kill Switches” 가 있습니다. 즉 수동 circuit breaker라고 볼 수 있습니다.

**Permission toggle:**

특별 사용자에게만 제공하고 싶은 기능, 예로 베타 서비스 테스트 중 사용, toggle입니다. canary toggle도 여기에 속합니다. 임시적으로 사용되고, 동적으로 변경할 수 있어야 하는 기능으로 지속적인 permission관리 시스템과는 별도로 사용됩니다.

### 3. django-waffle

[https://waffle.readthedocs.io/en/stable/](https://waffle.readthedocs.io/en/stable/)

feature toggle구현은 여러 방법이 있습니다. 본 문서에서는 그 중 DB를 사용하는 django library를 소개해 드리려고 합니다. 

![[https://djangopackages.org/grids/g/feature-flip/](https://djangopackages.org/grids/g/feature-flip/)](../images/feature_flags/Untitled%203.png)

[https://djangopackages.org/grids/g/feature-flip/](https://djangopackages.org/grids/g/feature-flip/)

기본적으로 cache를 사용하여 DB부하를 줄이고 있습니다. cache ttl은 django default cache ttl로 확인됐습니다. cache flush는 flag / switch 객체 save시 cache `delete_many`로 관리 중인 cache를 전부 삭제 하는 방식을 사용 중입니다.

기본 설정 값:

```python
WAFFLE_SWITCH_DEFAULT = False   # automatically created switch value
WAFFLE_FLAG_DEFAULT = False     # automatically created flag value
WAFFLE_CREATE_MISSING_SWITCHES = True # automatically create switch if does not exist
WAFFLE_CREATE_MISSING_FLAGS = True # automatically create flag if does not exist
```

사용 예시:

switch는 str을 구분값으로 bool를 저장하는 자료구조입니다.

```python
from waffle import switch_is_active

def example_function(*args, **kwargs):
	if switch_is_active('example_function_switch'):
		# active: new code
	else:
		# inactive: old code
```

flag는 user, group, authentication, superuser 등 정보로 기준값에 맞는 bool를 저장하는 자료구조입니다. django request 객체로 요청 정보를 추출하여 condition 검증을 합니다.

```python
from waffle import flag_is_active

def example_function(request, *args, **kwargs):
	if flag_is_active(request, 'example_function_flag'):
		# active: new code
	else:
		# inactive: old code
	pass
```

decorator만 사용하여 class method을 분기할 수 있습니다(구현필요, ref: [당근기술블로그](https://medium.com/daangn/%EB%A7%A4%EC%9D%BC-%EB%B0%B0%ED%8F%AC%ED%95%98%EB%8A%94-%ED%8C%80%EC%9D%B4-%EB%90%98%EB%8A%94-%EC%97%AC%EC%A0%95-2-feature-toggle-%ED%99%9C%EC%9A%A9%ED%95%98%EA%B8%B0-b52c4a1810cd))

```python
class ExampleSerializer(serializer.Serializer):

		def validate(self, attr):
				# some logic
				ret = self.existing_func(attr['key1'], attr['key2'])
				# some logic
				return ret

    @feature_toggle_method(key='ExampleView_NEW_COOL_FEATURE', fallback_method=ExampleSerializer.new_func)
    def existing_func(self, arg_1, arg_2):
		    # this will fallback to new_func if toggle is set
        # old logic
        return None
    
    def new_func(self, arg_1, arg_2):
        # new logic
        return None
```

class decorator로 분기 할 수 도 있습니다(구현필요)

```python

# Example usage
@feature_toggle_cls('ExampleFeatureToggle', fallback_class=NewSerializer)
class OldSerializer(serializer.Serializer):
    def __init__(self):
        print("OldSerializer instance created")

class NewSerializer(serializer.Serializer):
    def __init__(self):
        print("NewSerializer instance created")

# Depending on the toggle state, creating an instance of OldSerializer
# will actually create an instance of either OldSerializer or NewSerializer.
def ViewClass(view.APIView):
		serializer_class = OldSerializer
    ....

```

function decorator로 function 분기(구현필요)

```python

@feature_toggle_func('ExampleFeatureToggle', fallback_function=new_func)
def old_func(arg_1, arg_2):
		# old logic
		return None
		
def new_func(arg_1, arg_2):
		# new logic
		return None
```

django-waffle은 django orm migration, admin을 지원하여, django migration으로 디비의 switch, flag값을 관리 할 수 있습니다.

코드 배포 전 미리 배포대상 admin에서 객체(flag, switch)를 생성하거나, `AFFLE_CREATE_MISSING_SWITCHES` ,  `WAFFLE_CREATE_MISSING_FLAGS`설정으로 조회 시 자동 생성 되는 기능이 있습니다. 생성 된 flag, switch는 admin에서 관리 가능합니다.

![Untitled](../images/feature_flags/Untitled%204.png)

![Untitled](../images/feature_flags/Untitled%205.png)

unittest 예시

```python
from waffle.testutils import override_flag, override_sample

with override_flag('flag_name', active=True):
    # Only 'flag_name' is affected, other flags behave normally.
    assert waffle.flag_is_active(request, 'flag_name')
    
...

@override_sample('sample_name', active=True)
def test_with_sample():
    # Only 'sample_name' is affected, and will always be True. Other
    # samples behave normally.
    assert waffle.sample_is_active('sample_name')
```

### 4. 예외

toggle 적용이 어려운 경우가 있습니다.

- toggle간에 의존성이 있는 경우
- nested toggles:
    - toggle이 적용된 한 기능 내부에 toggle이 있는경우

이런 경우는 아래의 방법으로 해결할 수 있습니다.

1. dependency graph를 문서화, toggled feature rollout 방법 정리
2. 서로 호환 가능하도록 예외처리 코드 추가
3. 리팩토링, feature toggle 통합
4. function decorator 혹은 class decorator활용 toggle 분기를 모듈화 하여 nested나 dependency를 줄인다

해결이 불가능 한 경우도 있습니다.

- 시스템 구조 변경:
    - 구조가 변경되거나 toggle로 버전을 변경 못 하는 경우, 연동 시스템의 의존성 등
- binary 파일, json document 파일 포멧이 변경 경우
- 디비 이전(예 Mysql → Postgres)
- 코드 구조 리팩토링 경우

이럴 경우에는 major 버전 업데이트로 간주하고, 기존 배포방법을 사용합니다.

### 5. clean-up

toggle을 유지하며 코드 크기가 계속 커지는 이슈와 DB접근 overhead가 발생합니다. 테스트 CI도 무시할 수 없습니다. 릴리즈 후 검증되고 사용하지 않는 toggle은 빠른 시내에 정리가 필요합니다.

Toggle의 생성 시기와 기한을 명시하여 관리 기간을 추적하고, 만료된 toggle은 팀에 알림을 통해 주의를 환기시킵니다.

기한이 만기 된 toggle은 CI실패를 유발하여 관리를 강제하는 방법도 있습니다.

### 6. 테스트

모든 추가된 toggle 기능에 대해서는 단위 테스트나 수동 테스트가 필수적입니다. toggle 키기 전 문제 없던 서버가 (특히 dynamic typed language경우) 실행 후 syntax에러 같은 문제로 시스템이 다운 될 수 도 있기 때문입니다.

## 🔚 Endpoint versioning

feature toggle로 기능의 버전을 조정하는 방법이 있지만 REAT API의 구조를 활용하는 방법도 있습니다.

`/api/v3/ecg-tests/{tid}`의 새로운 endpoint를 추가함으로써 버전 관리를 할 수 있습니다.

아래 처럼 minor버전, hotfix 버전을 포함하여, 최근 추가/수정 된 기능을 분리할 수 있습니다.

- `/api/v3.0.0/ecg-tests/{tid}`
- `/api/v3.1.0/ecg-tests/{tid}`

아니면 버전명을 날짜로도 관리 하는 방법 도 있습니다

- `/api/20240322/ecg-tests/{tid}`

이 방법은 별도의 view나 serializer를 분리 할 때 유용합니다.

## ↩️ 하위호환 schema

디비 schema는 라이브 서버에서 전 후 버전을 이전 할 수 없습니다. 이 경우 하위호환가능한 schema로 설계하여 feature toggle 시 전 버전에서도 동일하게 동작하도록 되어야 합니다.

1. 필드 삭제 지양:
필드를 사용하는 기능(toggle)이 있을 경우 삭제하지 않는다.
사용하지 않는다면 toggle clena-up을 할 때 같이 삭제한다.
2. 필드 기본값:
설계 시 `null=True, default=None`등 기본값이 항상 있도록 합니다.
필드 수정(아래 내용) 시 평소 필수로 입력 되 던 필드가 입력이 안될 경우가 있습니다.
3. 필드 수정 지양:
필드의 constraint나 type을 변경을 지양합니다. 수정이 필요 시 신규 필드를 만들고 신규 버전 serializer에서 호환을 고려하여 getter, setter를 추가해야 합니다. 필요 시 수동 migration으로 동기화 합니다.
예를 들면 type을 수정 할 시(예. str → enum) 이전버전 로직에서는 기존그대로 저장하고, 신규버전에서는 저장 시 신규필드로 저장, 읽을 시 에는 신규필드에 값이 있는지 확인 후 없을 경우 이전 필드 데이터 사용 및 신규로 이전 하는 로직추가가 필요합니다. 신규 배포 기능 동작 검증 된 후 기존필드를 신규로 이전하는 migration script를 실행 해 모든 데이터가 동기화 되 도록 합니다. 이전 toggle 삭제 시 기존 필드 삭제 및 연관 코드 삭제를 할 수 있습니다.

## 👁️‍🗨️ PR 리뷰 간소화

현재 release에 PR로 리뷰를 하는 방식에서 develop으로 PR리뷰를 하고, develop → release, release → main PR은 리뷰를 거치지 않는 방법입니다.

GitHub Flow를 채택하여 release와 main으로의 머지 과정에서 PR 및 리뷰를 줄임으로써 개발자의 관리 부담을 줄일 수 있습니다.

예외로, hotfix같은 바로 release나 main으로 기능 PR을 하는 경우는 리뷰를 거치도록 할 수 있습니다.

## 💰 유지관리 비용

feature toggle은 특히 처음 도입될 때 빠르게 늘어나는 경향이 있습니다. 가장 간단하게 구현하면 큰 초기비용이 들지는 않지만, 유지할 시 발생하는 overhead가 있습니다. 코드에 새로운 추상화나 조건부 로직을 추가해야 합니다. 그리고 테스트 부담도 초래합니다.. [Knight Capital Group의 4억 6,000만 달러 실수](https://dougseven.com/2014/04/17/knightmare-a-devops-cautionary-tale/)는 feature toggle을 올바르게 관리하지 않을 때 어떻게 잘못될 수 있는지에 대한 경고를 보여주고 있습니다.
(ref: [https://sungjk.github.io/2022/10/15/feature-toggles.html](https://sungjk.github.io/2022/10/15/feature-toggles.html))

## 👍 장점

- 릴리즈 날짜나 FE 배포를 기다리지 않고 Dev, QA, Prod 환경에 자유롭게 배포가 가능합니다. 즉 배포와 릴리즈 분리
- 배포 순서 때문에 발생하는 branch관리이슈로 부터 자유로워 집니다.
- git 통합 cycle 축소
- 장애나 버그 발견 시 재배포 없이 바로 이전 버전으로 rollback이 가능합니다.
- 특정 사용자나 사용케이스에 따라 Prod에서 테스트가 가능합니다.
- 재배포 없이 기능 canary 배포가 가능합니다.
- A/B 테스트가 가능합니다.

## 👎 단점

- 신규 기능마다 버전 분기 코드 추가가 필요합니다. 개발 비용이 늘어 날 수 있습니다.
- 디비 schema 하위호환 위한 비용이 발생합니다.
- 주기적으로 사용하지 않는 toggle들 정리가 필요합니다.
- DB저장소 사용 시, cache를 할 수 있지만, toggle 분기 확인의 부하가 있습니다.
- 구조 적 변경이나 major 업데이트에는 적용이 불가능합니다.

## 🔖 Case Study

### 11번가

[https://11st-tech.github.io/2023/11/07/openfeature/](https://11st-tech.github.io/2023/11/07/openfeature/)

### 당근

[https://medium.com/daangn/매일-배포하는-팀이-되는-여정-2-feature-toggle-활용하기-b52c4a1810cd](https://medium.com/daangn/%EB%A7%A4%EC%9D%BC-%EB%B0%B0%ED%8F%AC%ED%95%98%EB%8A%94-%ED%8C%80%EC%9D%B4-%EB%90%98%EB%8A%94-%EC%97%AC%EC%A0%95-2-feature-toggle-%ED%99%9C%EC%9A%A9%ED%95%98%EA%B8%B0-b52c4a1810cd)

### 배달의민족

[https://techblog.woowahan.com/9935/](https://techblog.woowahan.com/9935/)

### 구글

[https://medium.com/firebase-developers/remote-config-feature-flagging-a-full-walkthrough-9b2f2188bb47](https://medium.com/firebase-developers/remote-config-feature-flagging-a-full-walkthrough-9b2f2188bb47)

### 맘시터

[https://tech.mfort.co.kr/blog/2022-11-24-feature-toggle/](https://tech.mfort.co.kr/blog/2022-11-24-feature-toggle/)

### 그린랩스

[https://green-labs.github.io/feature-flags-1](https://green-labs.github.io/feature-flags-1)
