Title: 무거운 SQL 쿼리 최적화: 5초 -> 300ms 개선과정
Date: 2026-03-12 16:52
Modified: 2026-03-12 16:52
Categroy: sql
Tags: sql, optimization, profile
Author: Isaac Park
Summary: 관리자 목록 조회의 5초짜리 SQL 병목을 프로파일링으로 원인을 분해하고, 불필요한 JOIN·ORM 로딩·N+1 쿼리를 제거해 300ms대로 개선한 최적화 사례

---

> 이 글에서 다루는 코드와 데이터는 기밀 유지를 위해 일부 이름과 용어를 익명화했습니다.

## 1. 현재 상황과 아키텍처

내부 관리 플랫폼에서 ChangeRequest(변경 요청) 관리 기능을 제공하고 있습니다. 사용자가 리소스의 배포, 중지, 재배포 등을 요청하면 권한을 가진 관리자가 이를 승인하거나 반려하는 구조입니다.

이번 글에서 다루는 문제는 단순히 “쿼리 하나가 느리다” 수준이 아니라, 목록 조회 전체가 여러 단계의 쿼리와 ORM 로딩 비용까지 겹치면서 응답 시간이 크게 증가하던 사례입니다.

### 데이터 모델

```text
ChangeRequest
  ├─ target_type (SERVICE, WORKFLOW, DASHBOARD, ...)
  ├─ target_version_id ──→ Version (ServiceVersion, WorkflowVersion, ...)
  ├─ submitter_id ──→ User
  └─ reviewer_id  ──→ User

Version ──→ Parent (Service, Workflow, Dashboard, ...)
Parent  ──→ TargetMeta ──→ ProjectSpace
```

### `change_request_tb` 스키마

| 컬럼                  | 타입               | 설명                                |
| ------------------- | ---------------- | --------------------------------- |
| `id`                | INT PK           |                                   |
| `target_type`       | VARCHAR          | SERVICE, WORKFLOW, DASHBOARD 등 6종 |
| `target_version_id` | INT              | Version/Deployment 테이블의 FK        |
| `submitter_id`      | INT FK → user_tb | 요청자                               |
| `reviewer_id`       | INT FK → user_tb | 승인자                               |
| `requested_action`  | VARCHAR          | Activate, Deactivate, Reactivate  |
| `review_status`     | VARCHAR          | NULL(대기), Approved, Denied        |
| `comment`           | TEXT             | 코멘트                               |

### 3-Phase 쿼리 구조

목록 조회는 3단계로 실행됩니다.

1. **Phase 1 (COUNT)**: `base_query`를 서브쿼리로 감싸 `SELECT count(*)`
2. **Phase 2 (PAGE IDs)**: `base_query`에서 `ORDER BY` + `OFFSET/LIMIT`으로 현재 페이지 ID 추출
3. **Phase 3 (DETAIL)**: `WHERE id IN (page_ids)`로 상세 데이터 조회

구조 자체는 흔한 패턴이지만, 실제 실행 결과는 꽤 무거웠습니다.

* **Admin 사용자 기준**: 144개 쿼리, 5,807ms
* **Non-admin 사용자 기준**: 110개 쿼리, 1,692ms

즉 병목은 단일 SQL 한 줄에만 있는 것이 아니라, COUNT / 페이지 조회 / 상세 조회 / ORM 추가 로딩이 모두 합쳐진 형태였습니다.

---

## 2. SQL 프로파일러

SQLAlchemy를 사용할 때는 ORM이 생성하는 실제 SQL과 바인드 파라미터, 그리고 각 쿼리의 실행 시간을 한눈에 보기 어렵습니다.
그래서 이번에는 커스텀 프로파일러를 만들어 아래 기능을 확인할 수 있도록 했습니다.

* 실제 실행 SQL 확인
* 파라미터 인라인
* 쿼리별 실행 시간 측정
* `SQL_NO_CACHE` 자동 주입

### SQLAlchemy 이벤트 훅

```python
@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("_query_start", []).append(time.perf_counter())

@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_execute(conn, cursor, statement, parameters, context, executemany):
    elapsed_ms = round(
        (time.perf_counter() - conn.info["_query_start"].pop()) * 1000, 3
    )
    _sql_profiles.append({
        "ms": elapsed_ms,
        "sql": _inline_params(statement, parameters),
    })
```

### 파라미터 인라인 헬퍼

```python
def _inline_params(stmt: str, params) -> str:
    """바인드 파라미터를 SQL에 직접 삽입하여 실행 가능한 쿼리 생성."""
    if isinstance(params, dict):
        escaped = {k: _escape(v) for k, v in params.items()}
        return re.sub(r"%\((\w+)\)s", lambda m: escaped.get(m.group(1), "NULL"), stmt)
    # ... tuple/list 처리
```

### `SQL_NO_CACHE` 컨텍스트 매니저

MySQL 쿼리 캐시 영향을 최대한 줄이고, 순수 실행 시간 경향을 보기 위해 `SQL_NO_CACHE`를 주입했습니다.

```python
@contextmanager
def mysql_sql_no_cache(engine):
    def _inject(conn, cursor, statement, parameters, context, executemany):
        stripped = statement.lstrip()
        if not stripped.upper().startswith("SELECT "):
            return statement, parameters
        return f"SELECT SQL_NO_CACHE {stripped[7:]}", parameters

    event.listen(sync_engine, "before_cursor_execute", _inject, retval=True)
    try:
        yield
    finally:
        event.remove(sync_engine, "before_cursor_execute", _inject)
```

### 프로파일 출력 예시

```text
======================================================================
  SQL PROFILE REPORT — 144 queries, 5807.37ms total
======================================================================

  [10] 🐢 SLOW  1677.123ms
  ------------------------------------------------------------------
  SELECT SQL_NO_CACHE count(*) FROM (SELECT ... ) AS anon_1

  [11] 🐢 SLOW  1666.456ms
  ------------------------------------------------------------------
  SELECT SQL_NO_CACHE anon_1.approval_id FROM (SELECT ... ) AS anon_1 ...
```

---

## 3. 프로파일 결과 분석

### 최적화 전 (Admin, 144 쿼리, 5,807ms)

| 쿼리 번호      | 소요시간         | 내용                                 |
| ---------- | ------------ | ---------------------------------- |
| [1]–[9]    | ~156ms       | 사전 설정 (statements, writable IDs 등) |
| [10]       | **1,677ms**  | Phase 1 — COUNT                    |
| [11]       | **1,666ms**  | Phase 2 — PAGE IDs                 |
| [12]       | 150ms        | Phase 3 — DETAIL                   |
| [13]–[144] | **~2,145ms** | ORM selectin cascade (132쿼리)       |

여기서 바로 보이는 것은 다음 두 가지입니다.

1. **Phase 1, 2가 비정상적으로 무겁다**
2. **Phase 3 이후 ORM 추가 쿼리가 과도하게 발생한다**

### 3가지 병목 식별

**병목 1**: Phase 1, 2의 `target_meta_tb` BNL join

`base_query`에 `target_meta_tb`가 6-arm OR 조건으로 outer join되어 있었습니다.

```python
base_query = (
    select(
        ChangeRequest.id.label('request_id'),
        # ...
        ProjectSpace.name.label('project_space_name'),  # ← 이것 때문에 join 필요
    )
    # ... 12개 revision/parent outerjoin ...
    .outerjoin(
        TargetMeta,
        or_(
            and_(TargetMeta.target_type == 'SERVICE',
                 TargetMeta.target_version_id == ServiceVersion.service_id),
            and_(TargetMeta.target_type == 'WORKFLOW',
                 TargetMeta.target_version_id == WorkflowVersion.workflow_id),
            # ... 4개 더
        )
    )
    .outerjoin(ProjectSpace, ProjectSpace.id == TargetMeta.project_space_id)
)
```

문제는 이 join이 COUNT와 PAGE IDs 단계에도 그대로 포함되어 있었다는 점입니다.
즉 실제로 아직 상세 데이터가 필요하지 않은 단계에서도, 무거운 join 비용을 계속 지불하고 있었습니다.

**병목 2**: Phase 3에서 ORM 객체 전체 SELECT → selectin cascade

```python
query = select(
    ChangeRequest,
    # ...
    ServiceVersion,          # ← ORM 객체
    AutomationRelease,       # ← ORM 객체
    Automation,              # ← ORM 객체
)
```

이렇게 ORM 객체 전체를 SELECT에 포함하면, 결과 반환 이후 SQLAlchemy가 `lazy='selectin'` 관계를 따라 추가 로딩을 수행할 수 있습니다.

이번 케이스에서는 이 비용이 매우 크게 나타났고, 결과적으로 **132개 추가 쿼리**가 발생했습니다.

**병목 3**: Non-admin N+1 `get_user_statements()`

```python
for request, ..., project_space_name in rows:
    if not is_admin:
        # 캐시 미스마다 DB 조회 발생
        updatable = await permission_service.can_user_create_resource(
            resource_type=request.target_type,
            project_space_name=project_space_name,
            ...
        )
```

권한 체크 자체는 필요하지만, 동일한 성격의 데이터를 반복 조회하면서 N+1 형태가 발생하고 있었습니다.

---

## 4. EXPLAIN ANALYZE로 쿼리 분석

Phase 1 COUNT 쿼리에 `ANALYZE SQL_NO_CACHE`를 실행했습니다.

| table              | type    | rows      | r_rows    | Extra                     |
| ------------------ | ------- | --------- | --------- | ------------------------- |
| change_request_tb  | ALL     | 6,428     | 6,293     | Using where               |
| service_version_tb | eq_ref  | 1         | 0.24      | Using where               |
| service_tb         | eq_ref  | 1         | 0.20      | Using where               |
| ...                | eq_ref  | 1         | ...       | ...                       |
| **target_meta_tb** | **ALL** | **5,173** | **5,177** | **Using where; BNL join** |

`change_request_tb` 6,293행과 `target_meta_tb` 5,177행이 결합되면서, 대략 **3,260만 번 수준의 비교 연산**이 발생하고 있었습니다.

즉 `OR` 기반 join 조건이 인덱스 활용을 어렵게 만들고, 그 결과 BNL(Block Nested Loop) 풀 스캔이 발생한 것입니다.

---

## 5. 근본 원인 분석

정리하면 병목은 아래 3가지로 분류할 수 있었습니다.

| # | 근본 원인                                                 | 영향 범위     | 소요시간               |
| - | ----------------------------------------------------- | --------- | ------------------ |
| 1 | Phase 1,2의 `target_meta_tb` + `project_space_tb` join | Phase 1+2 | 3,343ms (58%)      |
| 2 | Phase 3 ORM selectin cascade                          | 132 쿼리    | ~2,145ms (37%)     |
| 3 | N+1 `get_user_statements()`                           | ~14 쿼리    | ~170ms (non-admin) |

---

## 6. 수정 전략

수정 방향은 다음 3가지로 잡았습니다.

1. **Fix 1**: `base_query`에서 `target_meta_tb` / `project_space_tb` join 제거, Phase 3에서만 유지
2. **Fix 2**: Phase 3 SELECT에서 ORM 객체를 스칼라 컬럼으로 교체
3. **Fix 3**: `user_statements`를 사전 조회하여 동기 헬퍼에 전달

---

## 7. 테스트 먼저 — 회귀 방지

최적화 작업에서 종종 놓치기 쉬운 것이 “성능은 좋아졌는데 기능이 깨지는 문제”입니다.
그래서 코드 변경 전에 성능 회귀 테스트와 기능 회귀 테스트를 먼저 작성합니다.

### QueryCounter

```python
class QueryCounter:
    """SQLAlchemy 엔진의 쿼리 수와 총 소요시간을 측정하는 컨텍스트 매니저."""

    def __init__(self, engine):
        self.engine = engine.sync_engine
        self.queries = []

    def _before_execute(self, conn, cursor, stmt, params, context, executemany):
        conn.info.setdefault("_qc_start", []).append(time.perf_counter())

    def _after_execute(self, conn, cursor, stmt, params, context, executemany):
        start = conn.info["_qc_start"].pop()
        self.queries.append({'time': (time.perf_counter() - start) * 1000})

    def __enter__(self):
        self.queries.clear()
        event.listen(self.engine, "before_cursor_execute", self._before_execute)
        event.listen(self.engine, "after_cursor_execute", self._after_execute)
        return self

    def __exit__(self, *args):
        event.remove(self.engine, "before_cursor_execute", self._before_execute)
        event.remove(self.engine, "after_cursor_execute", self._after_execute)

    @property
    def count(self): return len(self.queries)

    @property
    def total_time_ms(self): return sum(q['time'] for q in self.queries)
```

### 성능 회귀 테스트

```python
async def test_admin_default_query_count(self, ...):
    with QueryCounter(engine) as qc:
        total, approvals = await list_change_requests(user=admin, pg=1, pg_size=10)

    assert total == 1000
    assert qc.count <= 25      # 쿼리 수 상한
    assert qc.total_time_ms < 500  # 시간 상한 (ms)

async def test_non_admin_default_query_count(self, ...):
    with QueryCounter(engine) as qc:
        total, _ = await list_change_requests(user=non_admin, pg=1, pg_size=10)

    assert total == 500
    assert qc.count <= 35
    assert qc.total_time_ms < 500
```

### 기능 회귀 테스트

성능 개선 과정에서 정렬, 필터 등 기존 기능이 깨지지 않았는지도 함께 검증합니다.
예를 들어 `base_query`의 join을 변경하면 ORDER BY 동작이 달라질 수 있으므로, 정렬 테스트를 미리 작성해 두었습니다.

```python
async def test_order_by_id_desc(self, ...):
    """ID 내림차순 정렬이 올바르게 동작하는지 검증."""
    await create_multiple_change_requests(
        session, admin, project_space, base_resources,
        count=10, prefix='order-test'
    )

    total, responses = await list_change_requests(
        user=admin, pg=1, pg_size=10,
        order_field=OrderField.id, order_type=OrderType.desc,
        session=session,
    )

    ids = [r.id for r in responses]
    assert ids == sorted(ids, reverse=True), "IDs should be in descending order"

async def test_order_by_target_type(self, ...):
    """target_type 정렬: asc와 desc가 서로 역순인지 검증."""
    await create_multiple_change_requests(
        session, admin, project_space, base_resources,
        count=12, prefix='order-test'
    )

    _, responses_asc = await list_change_requests(
        user=admin, pg=1, pg_size=20,
        order_field=OrderField.target_type, order_type=OrderType.asc,
        session=session,
    )
    _, responses_desc = await list_change_requests(
        user=admin, pg=1, pg_size=20,
        order_field=OrderField.target_type, order_type=OrderType.desc,
        session=session,
    )

    types_asc = [r.target_type for r in responses_asc]
    types_desc = [r.target_type for r in responses_desc]
    assert types_asc == list(reversed(types_desc))
```

이런 기능 테스트가 있으면 join을 제거하거나 SELECT 컬럼을 변경해도 **정렬/필터 동작 등 기능이 그대로인지 즉시 확인**할 수 있습니다.

### 테스트 데이터

* 1,000개 ChangeRequest (10개 ProjectSpace × 6개 target_type)
* `SQL_NO_CACHE` 자동 주입으로 MySQL 캐시 제거
* Admin / Non-admin 각각 검증
* 검색, 정렬, 필터 조합별 파라미터화 테스트

이 테스트로 **다시 느려지지 않도록 상한을 고정하는 역할**도 합니다.

---

## 8. 코드 수정 적용

### Fix 1: `base_query`에서 `target_meta_tb` join 제거

**Before** — Phase 1, 2 모두 `target_meta_tb` BNL join 포함

```python
base_query = (
    select(
        ChangeRequest.id.label('request_id'),
        # ...
        ProjectSpace.name.label('project_space_name'),
    )
    # ... revision/parent outerjoins ...
    .outerjoin(
        TargetMeta,
        or_(
            and_(TargetMeta.target_type == 'SERVICE',
                 TargetMeta.target_version_id == ServiceVersion.service_id),
            # ... 5개 더
        )
    )
    .outerjoin(ProjectSpace, ProjectSpace.id == TargetMeta.project_space_id)
    .where(...)
)
```

**After** — `target_meta_tb` / `project_space_tb` join 제거, Phase 3에서만 유지

```python
base_query = (
    select(
        ChangeRequest.id.label('request_id'),
        # ...
        # project_space_name 제거됨 — Phase 3에서만 필요
    )
    # ... revision/parent outerjoins 유지 ...
    # target_meta_tb, project_space_tb는 Phase 3에서만 사용
    .where(...)
)
```

핵심: **COUNT와 PAGE IDs 단계에서 필요하지 않은 join은 제거한다**는 것입니다.

### Fix 2: Phase 3 ORM 객체 → 스칼라 컬럼

**Before**

```python
query = select(
    ChangeRequest,
    # ...
    ServiceVersion,          # ORM 객체 전체 → selectin cascade 유발
    AutomationRelease,       # ORM 객체 전체
    Automation,              # ORM 객체 전체
)

for request, ..., svc_version, auto_release, automation in rows:
    if request.target_type == 'AUTOMATION':
        parent_id = auto_release.automation_id
        parent_name = automation.name
    # ...
    if svc_version is None:
        raise ...
    data.update(is_external=svc_version.is_external)
```

**After**

```python
query = select(
    ChangeRequest,
    # ...
    # 스칼라 컬럼만 조회 — ORM 로딩 방지
    ServiceVersion.is_external.label('is_external'),
    AutomationRelease.automation_id.label('auto_parent_id'),
    Automation.name.label('auto_name'),
)

for request, ..., is_external, auto_parent_id, auto_name in rows:
    if request.target_type == 'AUTOMATION':
        parent_id = auto_parent_id
        parent_name = auto_name
    # ...
    if is_external is None:
        raise ...
    data.update(is_external=is_external)
```

**실제로 사용하는 값이 몇 개 안 된다면 ORM 객체 전체를 읽을 이유가 없습니다.**
필요한 스칼라 컬럼만 가져오는 편이 훨씬 안전하고 예측 가능합니다.

### Fix 3: N+1 → 사전 조회 statements 전달

**Before**

```python
# 각 고유 (target_type, project_space_name) 쌍마다 DB 조회
updatable = await permission_service.can_user_create_resource(
    resource_type=request.target_type,
    user=user,
    project_space_name=project_space_name,
    session=session     # ← 내부에서 get_user_statements() DB 호출
)
```

**After**

```python
# 함수 시작 시 이미 조회한 user_statements 재사용
updatable = permission_service.can_user_create_resource_from_statements(
    statements=user_statements,   # ← 사전 조회된 데이터
    resource_type=request.target_type,
    project_space_name=project_space_name,
)
```

**반복 DB 조회를 제거하고 이미 읽은 데이터를 재사용**하도록 개선했습니다.

---

## 9. 최적화 후 프로파일 비교

### After (Admin, 19 쿼리, 337ms)

| 쿼리 번호     | 소요시간     | 내용                                         |
| --------- | -------- | ------------------------------------------ |
| [1]–[9]   | ~156ms   | 사전 설정 (statements, writable IDs)           |
| [10]      | **12ms** | Phase 1 — COUNT (target_meta join 제거)      |
| [11]      | **18ms** | Phase 2 — PAGE IDs (target_meta join 제거)   |
| [12]      | **45ms** | Phase 3 — DETAIL (target_meta BNL, 10행 입력) |
| [13]–[19] | ~106ms   | User → Role → Policy 관계 eager-load         |

### 전후 비교

| 항목                 | Admin 전        | Admin 후         | Non-admin 전 | Non-admin 후      |
| ------------------ | -------------- | --------------- | ----------- | ---------------- |
| 총 쿼리 수             | 144            | **19**          | 110         | **28**           |
| 총 소요시간             | 5,807ms        | **337ms (17×)** | 1,692ms     | **543ms (3.1×)** |
| Phase 1 (COUNT)    | 1,677ms        | **12ms**        | 62ms        | **32ms**         |
| Phase 2 (PAGE IDs) | 1,666ms        | **18ms**        | 52ms        | **26ms**         |
| Phase 3 (DETAIL)   | 150ms          | **45ms**        | 131ms       | **121ms**        |
| ORM selectin       | 132쿼리, 2,145ms | **0쿼리**         | 75쿼리, 900ms | **0쿼리**          |
| N+1 statements     | —              | —               | 14쿼리, 170ms | **0쿼리**          |

### 현재 병목 분포 (Admin 337ms)

```text
사전 설정 (46%) ████████████████████████
Phase 1+2  (9%) █████
Phase 3   (13%) ███████
User 관계 로딩 (31%) ████████████████
```

Fix 2로 리소스 객체의 selectin cascade(132쿼리)는 완전히 제거되었습니다. 남은 31%는 `ChangeRequest`의 `submitter`/`reviewer` → `User` → `Role` → `Policy` 관계의 eager-load로, 이번 최적화 대상과는 별개의 쿼리입니다.

---

## 10. 결론

3가지 수정을 통해 다음과 같은 개선을 얻었습니다.

* **Admin**: 5.8초 → 337ms (**17배 개선**)
* **Non-admin**: 1.7초 → 543ms (**3.1배 개선**)

| Fix | 내용                                   | 효과             |
| --- | ------------------------------------ | -------------- |
| 1   | Phase 1,2에서 `target_meta_tb` join 제거 | 3,343ms → 30ms |
| 2   | ORM 객체 → 스칼라 컬럼                      | 132쿼리 제거       |
| 3   | `user_statements` 사전 조회 전달           | 14쿼리 제거        |

### 핵심 교훈

* **ORM의 숨겨진 비용**
  `select(OrmModel)` 한 줄이 의도치 않은 추가 쿼리를 유발할 수 있습니다. 실제로 필요한 컬럼만 가져오는 것이 안전합니다.

* **프로파일러의 중요성**
  SQLAlchemy 이벤트 훅으로 파라미터 인라인과 타이밍을 수집하면, ORM이 숨기고 있는 실제 실행 비용을 드러낼 수 있습니다.

* **EXPLAIN이 보여주는 것**
  단순히 “느리다”가 아니라, 어떤 join 전략이 사용되었고 왜 비용이 커졌는지까지 확인할 수 있어야 합니다.

* **테스트 먼저**
  쿼리 수와 실행 시간의 상한을 테스트로 고정해 두면, 이후 리팩터링이나 기능 추가 시 성능 회귀를 훨씬 빨리 발견할 수 있습니다.

### 향후 개선 여지

* `COUNT(*) OVER ()` 윈도우 함수로 Phase 1+2 병합
* `target_meta_tb`에 `(target_type, target_version_id)` 복합 인덱스 추가
* `change_request_tb` 비정규화 (`parent_name` 컬럼 추가)
