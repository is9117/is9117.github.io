Title: OpenTelemetry + Langfuse 분산추적 시스템 구축
Date: 2026-05-21 14:00
Modified: 2026-05-21 14:00
Tags: backend, infra, observability, llm
Author: 박이삭
Category: infra
Summary: OpenTelemetry · Langfuse · ClickHouse 기반 LLM 서비스 분산 추적

## 글의 목적과 대상 독자

LLM을 직접 호출하거나 워크플로우/에이전트 형태로 서비스에 녹이는 일이 폭발적으로 늘면서, 분산 추적(distributed tracing)은 더 이상 "있으면 좋은 것"이 아니라 운영의 필수가 되었습니다. 토큰·비용·모델 응답·외부 API 호출·벡터 검색·가드레일까지 한 요청이 거쳐가는 hop 수가 워낙 많아져서, 표준 로그·메트릭만으로는 한 사용자 한 질문의 흐름을 따라가기 어렵습니다.

본 글은 다음 독자를 대상으로 작성했습니다.

- 분산 추적·OpenTelemetry를 처음 도입하거나 깊이 있게 다시 보고 싶은 백엔드/DevOps 엔지니어
- LLM·에이전트 서비스에 observability를 붙이려는 AI/ML 엔지니어
- OpenTelemetry의 LLM 특화 백엔드로 등장한 **Langfuse**와, 그 OLAP 저장소 **ClickHouse**를 어떻게 활용·최적화하는지 궁금한 분

목차는 다음과 같습니다.

1. Observability 개념 정리 — trace / span / context propagation, W3C TraceContext·Baggage, B3 비교
2. OpenTelemetry — 아키텍처·프로토콜·SDK·경쟁 기술·한계
3. Langfuse — LLM observability를 위한 매니지드/오픈소스 프레임워크
4. ClickHouse — Langfuse의 OLAP 엔진, 직접 쿼리해 vendor-independent로 사용하기
5. 서비스 통합 사례 — vendor lock-in 회피 설계·암호화 옵션·실제 코드 예제

---

## 1. Observability란?

### 1.1 세 가지 신호 — logs, metrics, traces

전통적으로 observability는 세 가지 데이터로 구성된다고 이야기합니다.

| 신호 | 답하는 질문 | 대표 도구 |
|---|---|---|
| **Logs** | "이 시점에 무슨 일이 있었나?" | ELK, Loki, Splunk |
| **Metrics** | "지금 어떤 상태인가? 추세는?" | Prometheus, Datadog, CloudWatch |
| **Traces** | "이 한 요청이 어디를 거쳐 어떻게 흘렀나?" | Jaeger, Zipkin, Tempo, Langfuse |

본 글은 세 번째인 **traces**를 다룹니다. LLM 서비스에서는 한 요청이 edge API → gateway → 워크플로우 러너 → 벡터 DB → 임베딩 서빙 → LLM 서빙 → 가드레일을 거치는 등 hop이 워낙 많고, 각 hop마다 토큰·duration·error를 같이 봐야 디버깅·요금 분석·성능 튜닝이 가능합니다.

### 1.2 Trace, Span, Context Propagation

세 개의 핵심 개념입니다.

- **Trace**: 1 요청의 전체 흐름. 사용자가 채팅 한 번 입력한 후 응답을 받기까지가 1 trace.
- **Span**: trace를 구성하는 개별 작업 단위. "edge가 gateway에게 POST 요청을 보냄", "워크플로우가 LLM 서빙을 호출함" 등 각각이 1 span. 부모-자식 관계로 트리를 이룹니다.
- **Context Propagation**: trace의 식별자(`trace_id`)·부모 span 식별자(`span_id`)·기타 비즈니스 컨텍스트를 서비스 사이에서 어떻게 전달할지 정의한 규칙. HTTP 헤더로 전달하는 게 일반적입니다.

```
[trace_id=ab12...c9d3]
chat-edge (root span)
  └── gateway (child span)
        └── workflow (child span)
              ├── vector-search (child span)
              ├── embedding-serving (generation span) [model=bge-m3, tokens=128]
              └── llm-serving (generation span) [model=gpt-4o, input=1520, output=380]
```

위 그림에서 모든 span은 **같은 `trace_id`** 를 공유하면서 부모-자식 관계로 묶입니다. 이 묶임을 가능하게 하는 게 context propagation입니다.

### 1.3 W3C Trace Context

분산 추적 헤더의 사실상 표준은 W3C **Trace Context**입니다. 두 헤더로 구성됩니다.

#### traceparent

```
traceparent: 00-{trace_id 32hex}-{span_id 16hex}-{flags 2hex}
예) traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

| 필드 | 길이 | 의미 |
|---|---|---|
| `version` | 1 byte (2 hex) | 현재 `00` |
| `trace-id` | 16 byte (32 hex) | trace 식별자 |
| `parent-id` | 8 byte (16 hex) | 호출 측 span 식별자. 수신 측은 이 span을 부모로 삼아 새 span 생성 |
| `trace-flags` | 1 byte (2 hex) | `01` = sampled, `00` = not sampled |

#### tracestate

벤더 특화 메타데이터를 키-값으로 운반할 수 있는 헤더입니다. 여러 백엔드(Jaeger, Datadog 등)를 거치는 환경에서 각자의 컨텍스트를 잃지 않게 합니다.

```
tracestate: vendor1=value1,vendor2=value2
```

### 1.4 W3C Baggage

`traceparent`는 trace 위상만 전달하지 비즈니스 컨텍스트는 못 담습니다. 그 빈자리를 채우는 게 **Baggage**입니다.

```
baggage: userId=u123,sessionId=s456,tenant=acme
```

baggage에 실린 키들은 OpenTelemetry SDK가 자동으로 모든 span의 속성으로 복사할 수 있어, `사용자 X의 모든 trace 보기`·`세션 Y의 한 대화 묶음 보기` 같은 쿼리가 자연스럽게 가능해집니다.

### 1.5 B3와의 비교

W3C 전에 사실상 표준 위치를 차지했던 게 Twitter Zipkin이 만든 **B3** 헤더입니다. Istio 서비스 메시도 기본은 B3를 씁니다.

| 항목 | B3 (Multi-header) | B3 single | W3C Trace Context |
|---|---|---|---|
| 헤더 수 | 4 (`x-b3-traceid`, `x-b3-spanid`, `x-b3-parentspanid`, `x-b3-sampled`) | 1 (`b3`) | 1 (`traceparent`) + 1 (`tracestate`) |
| trace_id 길이 | 64-bit 또는 128-bit | 동일 | 128-bit 고정 |
| span_id 길이 | 64-bit | 64-bit | 64-bit |
| baggage | 별도 (`baggage-*` 접두사) | 별도 | 표준 `baggage` 헤더 |
| 표준화 주체 | Zipkin/OpenZipkin | 동일 | W3C |
| 도입 시점 | Zipkin 시대 (2012~) | 후속 | 2020 W3C Recommendation |

OpenTelemetry SDK는 두 propagator를 모두 내장하고 있어 `OTEL_PROPAGATORS=tracecontext,baggage,b3` 처럼 같이 켤 수 있습니다. 신규 시스템이라면 **W3C TraceContext + Baggage 조합**을 권장합니다.

---

## 2. OpenTelemetry

### 2.1 등장 배경

OpenTelemetry(약칭 **OTel**)는 **OpenTracing**과 **OpenCensus** 두 진영의 통합 산물입니다.

- OpenTracing(2016, CNCF): API 표준 중심, vendor-neutral
- OpenCensus(2017, Google): SDK + 자동 계측 라이브러리 풍부

두 프로젝트가 비슷한 목표를 다른 방식으로 풀고 있어 사용자가 어느 쪽을 골라야 할지 혼란이 컸고, 2019년에 합쳐 OpenTelemetry가 되었습니다. 2021년 CNCF Incubating, 그 후 OTel은 Kubernetes에 이어 CNCF에서 **두 번째로 활발한 프로젝트**가 됐습니다.

### 2.2 아키텍처

```
┌─ Application ──────────────────────┐
│  OTel API  (vendor-neutral 계측)    │
│  OTel SDK  (TracerProvider,         │
│             SpanProcessor,          │
│             Exporter)               │
└──────┬──────────────────────────────┘
       │ OTLP/HTTP or OTLP/gRPC
       ▼
┌─ OTel Collector (선택) ──────────────┐
│  Receivers → Processors → Exporters │
│  (배치, 필터링, 변환, fan-out)        │
└──────┬──────────────────────────────┘
       │ 여러 백엔드로 라우팅
       ▼
  Jaeger / Tempo / Datadog / Langfuse / ...
```

- **OTel API**: 애플리케이션 코드가 호출하는 인터페이스. 구현체에 의존하지 않습니다.
- **OTel SDK**: API의 실제 구현체. span을 만들고 처리해 exporter에 넘깁니다.
- **OTel Collector**: 별도 사이드카/데몬 프로세스. SDK가 직접 백엔드로 보내도 되지만, 라우팅·변환·배치·재시도를 한 곳에 모으려면 Collector를 둡니다. 백엔드가 1개고 변환이 필요 없으면 생략 가능합니다.

### 2.3 프로토콜 — OTLP

OTel의 정식 와이어 프로토콜은 **OTLP (OpenTelemetry Protocol)** 입니다.

| 전송 | 인코딩 | 엔드포인트 예 |
|---|---|---|
| gRPC | Protobuf | `:4317`, path: `/opentelemetry.proto.collector.trace.v1.TraceService/Export` |
| HTTP | Protobuf 또는 JSON | `:4318`, path: `/v1/traces` (Langfuse는 `/api/public/otel/v1/traces`) |

페이로드 구조(축약):

```protobuf
message ExportTraceServiceRequest {
  repeated ResourceSpans resource_spans = 1;
}
message ResourceSpans {
  Resource resource = 1;          // service.name, k8s.pod.name, ...
  repeated ScopeSpans scope_spans = 2;
}
message ScopeSpans {
  InstrumentationScope scope = 1; // tracer 이름·버전
  repeated Span spans = 2;
}
message Span {
  bytes trace_id = 1;             // 16 bytes
  bytes span_id = 2;              // 8 bytes
  bytes parent_span_id = 4;
  string name = 5;
  fixed64 start_time_unix_nano = 7;
  fixed64 end_time_unix_nano = 8;
  repeated KeyValue attributes = 9;
  Status status = 15;
  // ...
}
```

#### trace_id / span_id 포맷

| 항목 | 크기 | 표현 | 비고 |
|---|---|---|---|
| `trace_id` | 16 byte / 128-bit | 32-자리 hex | 0이면 invalid |
| `span_id` | 8 byte / 64-bit | 16-자리 hex | 0이면 invalid |

128-bit trace_id는 UUID와 같은 크기입니다. 기존 UUID 기반 trace 시스템에서 마이그레이션할 때, UUID의 dash만 제거하면 그대로 OTel trace_id로 승계할 수 있습니다.

### 2.4 SDK 구성 요소

Python SDK 기준으로 핵심 객체를 짚어 보면 다음과 같습니다.

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.propagate import set_global_textmap
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagators.composite import CompositePropagator

# 1) Resource — 모든 span에 붙는 프로세스 차원의 속성
resource = Resource.create({
    "service.name": "edge-api",
    "deployment.environment": "prod",
})

# 2) TracerProvider — Span 발급 공장
provider = TracerProvider(resource=resource)

# 3) Exporter — 어디로 보낼지
exporter = OTLPSpanExporter(endpoint="http://otel-backend:4318/v1/traces")

# 4) SpanProcessor — 어떻게 보낼지 (Batch 권장)
provider.add_span_processor(BatchSpanProcessor(exporter))

trace.set_tracer_provider(provider)

# 5) Propagator — 어떻게 전파할지
set_global_textmap(CompositePropagator([
    TraceContextTextMapPropagator(),
    W3CBaggagePropagator(),
]))
```

### 2.5 Instrumentation — Auto vs Manual

#### Auto-instrumentation

각 라이브러리에 monkey-patch를 적용해 자동으로 span을 만들고 헤더를 inject/extract합니다. 대표적으로 다음 4개를 활성화하면 Python 백엔드에서는 사실상 사람이 추가 코드 한 줄 없이 분산 추적이 됩니다.

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

FastAPIInstrumentor.instrument_app(app, excluded_urls="health,healthcheck")
AioHttpClientInstrumentor().instrument()
HTTPXClientInstrumentor().instrument()
RequestsInstrumentor().instrument()
```

#### Manual instrumentation

자동 계측이 닿지 않는 곳(파이썬 step 함수, RabbitMQ consumer 등)은 명시적으로 span을 만듭니다.

```python
tracer = trace.get_tracer("my.module")

with tracer.start_as_current_span("vector-search") as span:
    span.set_attribute("vdb.collection", collection_name)
    span.set_attribute("vdb.query", query)
    docs = await vdb.search(query)
    span.set_attribute("vdb.result_count", len(docs))
```

### 2.6 커스터마이징

실무에서 거의 무조건 한 번은 건드리게 되는 포인트입니다.

| 커스터마이징 | 용도 |
|---|---|
| `IdGenerator` | trace_id 생성 로직 교체 (예: 레거시 UUID 승계) |
| 커스텀 `TextMapPropagator` | 자사 헤더(`x-mycorp-trace-id`)를 W3C와 병행 |
| 커스텀 `SpanProcessor` | 헬스체크·내부 polling span 필터링, baggage → attribute 자동 복사 |
| 커스텀 Resource Detector | K8s pod·node·container 정보 자동 부착 |
| Sampler | head sampling (`ParentBased`, `TraceIdRatioBased`), tail sampling |

예시: 라우트 일부를 trace에서 빼고 baggage를 attribute로 자동 복사하는 셋업.

```python
from opentelemetry.processor.baggage import BaggageSpanProcessor, ALLOW_ALL_BAGGAGE_KEYS

provider.add_span_processor(BaggageSpanProcessor(ALLOW_ALL_BAGGAGE_KEYS))
provider.add_span_processor(BatchSpanProcessor(exporter))

FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls=",".join(["health", "healthcheck", "/auth/", "/metrics"]),
    exclude_spans=["receive", "send"],  # ASGI internal 0ms span 제거
)
```

### 2.7 유사·경쟁 기술

OTel가 등장하기 전, 그리고 지금도 병행 사용되는 도구들입니다.

| 시스템 | 위치 | OTel와의 관계 |
|---|---|---|
| **Jaeger** | trace backend (CNCF) | OTLP 수신 가능. UI·storage 제공 |
| **Zipkin** | trace backend | OTLP 수신 가능. B3 헤더의 본거지 |
| **Grafana Tempo** | trace backend | OTLP 네이티브, 비용 최적화 |
| **Datadog APM** | SaaS APM | OTLP 수신 또는 dd-trace SDK |
| **AWS X-Ray** | SaaS APM | OTel via ADOT(AWS Distro for OTel) |
| **Honeycomb / Lightstep** | SaaS observability | OTLP 네이티브 |
| **Elastic APM** | self-host/SaaS | OTel intake |
| **Langfuse** | LLM trace backend | OTLP `/api/public/otel/v1/traces` 직접 수신 |

핵심 관찰: 거의 모든 backend가 **OTLP 수신을 지원**합니다. 그래서 애플리케이션은 OTel SDK 하나로 작성하고, 백엔드 교체는 endpoint URL만 바꾸는 식의 비-침습 마이그레이션이 가능합니다.

### 2.8 한계

- **카디널리티 폭주**: span attribute에 user_id·request_id 등 high-cardinality 값을 무분별하게 박으면 backend의 index 크기가 폭증합니다. 1급 필터 키와 그렇지 않은 키를 구분해 설계하는 게 필수입니다.
- **Sampling tradeoff**: head sampling은 싸지만 결정 시점에 trace 끝을 못 봅니다(에러 trace가 버려질 위험). tail sampling은 정밀하지만 Collector 메모리·CPU 부담.
- **시맨틱 컨벤션의 진화**: `gen_ai.*` semantic convention은 2024~2025년에도 활발히 변경 중. 키 이름이 deprecate되거나 추가될 수 있으니 가능하면 추상화 레이어 한 겹.
- **Cold path overhead**: BatchSpanProcessor 큐가 가득 차거나 exporter가 느려지면 application latency에도 영향. 큐 size·flush interval 튜닝 필요.
- **SDK 안정성 차이**: language별로 SDK·instrumentation 라이브러리의 성숙도가 다릅니다. Python·Java·Go·Node.js는 GA, 나머지는 beta 또는 partial.

---

## 3. Langfuse — LLM observability framework

### 3.1 왜 LLM 전용 backend가 필요한가

Jaeger·Tempo 등 일반 trace 백엔드는 span tree·duration·error 위주의 분석에 최적화돼 있어 LLM 특유의 요구를 잘 못 받아냅니다.

- 모델별 input/output 토큰 합산·비용 산출
- 프롬프트 버전 추적·A/B 테스트
- 사용자 피드백 점수 부착
- LLM 응답에 대한 사람·평가 모델의 scoring
- 대용량 input/output 본문(수십 KB ~ 수 MB) 저장

Langfuse는 이 영역을 정조준한 오픈소스/매니지드 LLM observability 플랫폼입니다.

### 3.2 주요 기능

| 기능 | 설명 |
|---|---|
| Tracing | OTel OTLP 네이티브 수신. trace tree·duration·error 표준 기능 |
| Large I/O 저장 | 큰 사이즈(예 256 KB 초과) input/output을 별도 object storage(MinIO/S3)로 오프로드, span에는 reference token만 |
| 비용·토큰 트래킹 | 모델별 단가 카탈로그 내장. `gen_ai.usage.*` 또는 `langfuse.observation.usage_details` 속성으로 자동 합산 |
| Scoring / Feedback | trace·observation에 사람·모델 평가 점수 부착 (numeric/boolean/categorical) |
| Prompt Management | 프롬프트 템플릿 버저닝, A/B 테스트, trace와 prompt 연결 |
| Dashboard | 모델별·세션별·사용자별 비용·latency·error 시각화 |

### 3.3 아키텍처

self-host 기준 한 클러스터 안에 다음이 떠 있습니다.

```
┌─ Langfuse Stack ────────────────────────────────────┐
│                                                     │
│  ┌─────────────┐         ┌──────────────┐           │
│  │ langfuse-web│         │langfuse-worker│          │
│  │  (Next.js)  │         │  (Node.js)   │           │
│  │  UI + API   │         │  Queue worker│           │
│  └──────┬──────┘         └──────┬───────┘           │
│         │                       │                   │
│  ┌──────┴──────┐ ┌────────┐    │  ┌─────────────┐   │
│  │ PostgreSQL  │ │ Redis  │◀───┘  │ ClickHouse  │   │
│  │ (사용자/세션   │ │  (큐)  │       │ (telemetry) │   │
│  │  /트랜잭션)   │ └────────┘       │  3 replica  │   │
│  └─────────────┘                  └─────────────┘   │
│                                                     │
│            ┌────────────────┐                       │
│            │     MinIO      │ ← 대용량 input/output   │
│            │  (S3 호환)      │                       │
│            └────────────────┘                       │
└─────────────────────────────────────────────────────┘
```

| 컴포넌트 | 역할 |
|---|---|
| **Web** | UI(Next.js), Public API, OTLP/HTTP receiver, tRPC server |
| **Worker** | Redis 큐 consume → 정규화·indexing → ClickHouse·MinIO 적재 |
| **ClickHouse** | telemetry 메인 OLAP 저장소 (trace·observation·score) |
| **PostgreSQL** | 트랜잭셔널 데이터: 사용자/프로젝트/세션 설정/API key/Dashboard |
| **Redis** | 인입 이벤트 버퍼링 + 캐시 |
| **MinIO** | 대용량 input/output 원본, blob storage 추적 |

### 3.4 데이터 구조

| 엔티티 | 설명 | 저장 위치 |
|---|---|---|
| **Trace** | 1 요청의 최상위 단위. root span이 만들어내는 묶음 | ClickHouse `traces` |
| **Observation** | trace 내 개별 span. type은 `SPAN` / `GENERATION` / `EVENT` | ClickHouse `observations` |
| **Session** | 여러 trace를 묶는 그룹(`session.id`). 1 대화 = 1 session | `traces.session_id` 인덱스 |
| **User** | 사용자 식별자(`user.id`) | `traces.user_id` 인덱스 |
| **Score** | trace·observation에 부착되는 평가 점수 | ClickHouse `scores` |

### 3.5 Langfuse SDK · OTel · API 관계

세 가지 진입점이 모두 같은 백엔드를 향합니다.

| 진입점 | 언제 쓰나 | 특징 |
|---|---|---|
| **OTel SDK + OTLP** | 표준 분산 추적이 우선인 백엔드 | vendor-neutral. backend를 Jaeger 등으로 바꾸기 쉬움 |
| **Langfuse SDK** | LangChain·Flowise 등과 깊이 통합 | callback handler 한 줄로 LLM 호출 자동 추적, prompt 관리 등 native 기능 노출 |
| **Langfuse Public REST API** | 서버 측 직접 호출 | Score 부착, Media 업로드, batch ingest 등 |

**중요한 점**: Langfuse는 두 입구를 모두 받습니다. OTel SDK가 보낸 span도 Langfuse가 attribute prefix(`langfuse.trace.*`, `langfuse.observation.*`)를 인식해 UI 1급 필드로 매핑합니다.

### 3.6 Span emit flow

```
Application (OTel SDK, BatchSpanProcessor)
  │  POST {langfuse-web}/api/public/otel/v1/traces  (OTLP/HTTP, batch)
  ▼
langfuse-web (Next.js OTLP receiver)
  │  파싱 → 정규화 → 큐 publish
  ▼
MinIO (raw temp store)             ← 대용량 input/output 원본
  │
  ▼
Redis (queue)                       ← 인입 이벤트 버퍼링
  │
  ▼
langfuse-worker
  │  큐 consume → attribute 매핑
  ▼
┌─────────────────┐     ┌──────────────────┐
│ ClickHouse      │     │ PostgreSQL       │
│ traces /        │     │ session 트랜잭션   │
│ observations /  │     │ (필요한 경우)       │
│ scores          │     │                  │
└─────────────────┘     └──────────────────┘
```

### 3.7 공통 속성 — 무엇을 박아야 하나

모든 span이 가지면 좋은 attribute입니다.

| Attribute | 출처 | 비고 |
|---|---|---|
| `service.name` (Resource) | `OTEL_SERVICE_NAME` | 프로세스 식별 |
| `deployment.environment` (Resource) | 환경변수 | `dev` / `staging` / `prod` |
| `k8s.pod.name`, `k8s.namespace.name` | env / detector | 인프라 컨텍스트 |
| `http.request.method`, `http.route` | auto-instrumentation | HTTP 표준 |
| `user.id`, `session.id` | baggage | 사용자·세션 그룹핑 |

### 3.8 1급 메타데이터 vs catch-all (indexable)

Langfuse는 attribute prefix에 따라 ClickHouse 저장 위치가 달라집니다. **이게 검색·필터 가능 여부를 결정**합니다.

| Attribute prefix | ClickHouse 매핑 | 필터링 |
|---|---|---|
| `langfuse.trace.metadata.<key>` | `traces.metadata['<key>']` (Map column, bloom filter) | ✅ UI에서 직접 필터 |
| `langfuse.observation.metadata.<key>` | `observations.metadata['<key>']` (Map column, bloom filter) | ✅ UI에서 직접 필터 |
| 일반 OTel attribute (`http.request.method`) | `metadata['attributes']` JSON 문자열 | ❌ JSON 파싱 필요 |
| Resource attribute (`service.name`) | `metadata['resourceAttributes']` JSON 문자열 | ❌ 동일 |

설계 원칙: **검색·집계에 자주 쓸 key는 반드시 `langfuse.{trace,observation}.metadata.*` 접두사로 emit**. 무심코 박으면 ClickHouse에서 JSON 풀어내야 합니다.

### 3.9 토큰 사용량 속성

```python
span.set_attribute("langfuse.observation.type", "generation")

# OTel GenAI semantic convention
span.set_attribute("gen_ai.request.model", model)
span.set_attribute("gen_ai.response.model", actual_model)
span.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)
span.set_attribute("gen_ai.usage.output_tokens", completion_tokens)

# Langfuse native (둘 다 인식, 병행해도 OK)
span.set_attribute("langfuse.observation.model.name", model)
span.set_attribute("langfuse.observation.usage_details",
                   json.dumps({"input": prompt_tokens, "output": completion_tokens}))
```

`gen_ai.*` 와 `langfuse.*` 두 표준 모두 인식하므로, 다른 backend와 호환을 원하면 OTel 표준을 우선 박고 Langfuse-특화 키는 옵션으로 둡니다.

### 3.10 Input / Output 속성

```python
span.set_attribute("langfuse.observation.input", json.dumps(request_body))
span.set_attribute("langfuse.observation.output", json.dumps(response_body))
```

일정 크기(예 256 KB)를 초과면 Media API에 별도 업로드하고 reference token만 남기는 패턴도 있습니다.

```
@@@langfuseMedia:type=text/plain|id={22-char-base62}|source=file@@@
```

### 3.11 그 외 자주 쓰는 속성

| Attribute | 용도 |
|---|---|
| `langfuse.trace.name` | trace 표시 이름 (root span only) |
| `langfuse.trace.tags` | trace 태그 배열 |
| `langfuse.observation.level` | `DEBUG` / `DEFAULT` / `WARNING` / `ERROR` |
| `langfuse.observation.status_message` | 에러 메시지 |
| `langfuse.observation.prompt.name` | 프롬프트 관리와 연결 |
| `langfuse.observation.prompt.version` | 프롬프트 버전 |
| `langfuse.observation.completion_start_time` | TTFT (Time To First Token) |

---

## 4. ClickHouse — Langfuse의 OLAP 엔진

### 4.1 왜 ClickHouse를 이해해야 하나

Langfuse를 셋업해 두면 ClickHouse는 평소엔 보이지 않습니다. 그런데 다음 상황에서 ClickHouse 자체를 알아야 합니다.

- **vendor-independent 쿼리**: Langfuse Web API/UI를 거치지 않고 ClickHouse를 직접 쿼리하면 서비스 로직(예: 어드민 대시보드의 토큰 합산, CSV 다운로드)을 Langfuse에 묶지 않은 채 OTel standard에만 묶을 수 있습니다. Langfuse를 Tempo·Jaeger로 교체해도 쿼리 코드는 SQL 그대로.
- **고성능 쿼리**: 시계열·집계 쿼리는 ClickHouse columnar 엔진의 가장 강한 영역.
- **트러블슈팅**: 데이터 누락·중복·schema 마이그레이션을 디버깅하려면 SQL 직접 조회가 빠릅니다.

### 4.2 ClickHouse 특성

| 특성 | 의미 |
|---|---|
| **Columnar** | 컬럼별로 저장. 시계열·집계 쿼리에서 IO 효율이 매우 높음 |
| **Vectorized execution** | 한 번에 한 행씩 처리하지 않고 컬럼 chunk 단위로 SIMD 활용 |
| **MPP (Massively Parallel Processing)** | 노드·코어 단위 병렬 |
| **Read-optimized** | 대량 insert + 대량 scan에 최적. 단건 update/delete는 비효율 |
| **압축** | LZ4 / ZSTD codec, columnar 특성상 압축률 매우 높음 |

### 4.3 아키텍처

#### 4.3.1 스토리지 엔진 — MergeTree family

ClickHouse 테이블은 거의 모두 **MergeTree** 변종을 씁니다.

| 엔진 | 용도 |
|---|---|
| `MergeTree` | 기본 |
| `ReplicatedMergeTree` | ZooKeeper/Keeper 기반 replication |
| `ReplacingMergeTree` | 같은 정렬키 row가 들어오면 새 버전이 옛 버전을 덮어씀 (Merge 시점에) |
| `SummingMergeTree` | 같은 정렬키 row를 합산 |
| `AggregatingMergeTree` | aggregation state 저장 |
| `CollapsingMergeTree` | 양수/음수 sign 컬럼으로 row 삭제 표현 |

Langfuse는 `ReplicatedReplacingMergeTree`를 씁니다. 동일 id가 들어오면 `event_ts`가 큰 쪽이 최종으로 남고, 머지 완료 전엔 중복이 보일 수 있어 **쿼리에 `FINAL` 키워드를 붙이는 게 안전**합니다.

#### 4.3.2 쿼리 엔진

- Push-based pipeline
- Filter pushdown, projection pruning, partition pruning
- JOIN 알고리즘: hash, partial merge, parallel hash, grace hash 등 다양

#### 4.3.3 Quorum — ClickHouse Keeper

분산 ClickHouse는 메타데이터·replication 합의를 위해 ZooKeeper 또는 **ClickHouse Keeper** (자체 구현 Raft) 가 필요합니다. 최근에는 Keeper가 표준입니다.

- 클러스터당 보통 3 노드 (1 leader + 2 follower)
- DDL 동기화, replication queue, leader election 담당

#### 4.3.4 분산 아키텍처

| 개념 | 설명 |
|---|---|
| **Shard** | 데이터 수평 파티션. 한 shard는 여러 replica로 복제 가능 |
| **Replica** | 한 shard의 사본. read·HA·failover |
| **Distributed table engine** | shard들을 가상화한 fan-out 엔진. INSERT는 fan-out·라운드로빈, SELECT는 fan-out·merge |
| **Cluster** | shard·replica의 토폴로지를 정의한 논리 단위 |

```
                ┌──────── Distributed table ────────┐
                │  (no data, only metadata)         │
                └────┬─────────────┬─────────────┬──┘
                     ▼             ▼             ▼
              ┌─ Shard 1 ─┐  ┌─ Shard 2 ─┐ ┌─ Shard 3 ─┐
              │ Replica A │  │ Replica A │ │ Replica A │
              │ Replica B │  │ Replica B │ │ Replica B │
              │ Replica C │  │ Replica C │ │ Replica C │
              └───────────┘  └───────────┘ └───────────┘
                     ↑             ↑             ↑
                     └──── Keeper / ZooKeeper ────┘
```

#### 4.3.5 백업

- `BACKUP TABLE/DATABASE TO Disk('backups', ...)`/`RESTORE` 명령 (built-in)
- `clickhouse-backup` (Altinity)
- 파티션 freeze + 디스크 hardlink로 일관 스냅샷
- S3 backup destination 지원

#### 4.3.6 인덱스

| 종류 | 설명 |
|---|---|
| **Primary index** | ordering key 기준 sparse index. 8192 row 단위로 한 마크 |
| **Skip indexes** | secondary index 비스무리한 보조 구조. 아래 세 가지가 자주 쓰임 |
| `bloom_filter` | 키 존재 가능성 검사. equality 필터에 강함 |
| `minmax` | 컬럼의 min/max 캐시. range 필터에 강함 |
| `set(N)` | 컬럼의 distinct 값 set 캐시. 작은 cardinality에 강함 |

Langfuse는 `traces.metadata`·`observations.metadata` Map 컬럼의 key·value 모두에 bloom filter를 걸어 두어, `metadata['serving_id'] = '...'` 같은 쿼리가 인덱스로 가속됩니다.

#### 4.3.7 파티션

- `PARTITION BY toYYYYMM(timestamp)` 처럼 흔히 월별 파티션
- 파티션 단위로 `DROP`, `ATTACH`, `DETACH`, `FREEZE`, `TTL` 가능
- 쿼리 WHERE에 파티션 컬럼 조건이 있으면 **partition pruning**으로 검색 범위가 곧장 줄어듭니다

#### 4.3.8 기타 특수 기능

| 기능 | 설명 |
|---|---|
| **TTL** | row·column 단위 자동 만료/삭제, 또는 cold storage 이동 |
| **Materialized view** | INSERT 시 자동 트리거해 사전 집계 테이블 채움 |
| **Projection** | 같은 데이터의 다른 ordering·집계 버전을 한 테이블 안에 저장 |
| **Codec** | 컬럼별 압축 알고리즘 지정 (`Delta`, `DoubleDelta`, `Gorilla`, `ZSTD` 등) |
| **Dictionaries** | 외부 데이터(MySQL/HTTP 등)를 KV 형태로 in-memory 로드해 JOIN 대체 |

### 4.4 ClickHouse 쿼리 최적화

LLM trace 시나리오에서 효율 차이가 가장 큰 5가지입니다.

#### 4.4.1 `FINAL`로 중복 제거 보장

```sql
SELECT id, trace_id, start_time, end_time, metadata
FROM observations FINAL
WHERE trace_id = 'abc...'
```

`ReplacingMergeTree`에서 머지가 끝나기 전 중복 row를 거르려면 `FINAL`이 필요합니다. 비용이 있으니 **꼭 필요한 데이터셋**에만 사용. trace 상세처럼 데이터 정확성이 중요한 경로에서는 켜고, 대시보드 집계처럼 약간의 noise를 허용할 수 있으면 끄는 식.

#### 4.4.2 `project_id` 같은 정렬키 prefix 항상 명시

Langfuse의 ordering key는 `(project_id, type, toDate(start_time), id)`. 첫 키를 안 박으면 인덱스가 한 발도 작동 안 합니다.

```sql
SELECT ...
FROM observations FINAL
WHERE project_id = 'p123'        -- 필수
  AND type = 'GENERATION'        -- 두 번째 ordering key
  AND start_time >= '2026-05-01' -- partition pruning
```

#### 4.4.3 Partition pruning

`toYYYYMM(start_time)` 파티션이라면 WHERE에 `start_time BETWEEN ... AND ...`가 들어가야 partition pruning이 동작합니다. 날짜 범위 없는 쿼리는 풀스캔이 되니 주의.

#### 4.4.4 Map 컬럼 + bloom filter

```sql
SELECT count(), sum(toInt64OrZero(usage_details['input']))
FROM observations FINAL
WHERE project_id = 'p123'
  AND metadata['service'] = 'serving'
  AND metadata['resource_id'] = '484'
  AND start_time BETWEEN '2026-05-01' AND '2026-05-15'
```

`metadata['key']` equality 비교는 bloom filter로 가속됩니다.

#### 4.4.5 JOIN 시 양쪽 다 `FINAL`

```sql
SELECT o.id, o.trace_id, o.start_time, t.session_id, t.user_id
FROM observations FINAL AS o
LEFT JOIN traces FINAL AS t ON o.trace_id = t.id
WHERE o.project_id = 'p123'
  AND o.start_time BETWEEN '2026-05-01' AND '2026-05-15'
```

한쪽만 `FINAL`이면 중복이 JOIN에서 카르테시안으로 폭증할 수 있습니다.

---

## 5. 서비스 통합 — 실제 적용 사례

### 5.1 설계 원칙

본 절에서 소개하는 통합 전략의 뼈대입니다.

1. **OTel 표준 우선** — 애플리케이션 코드는 `opentelemetry.*` 패키지만 import. Langfuse SDK는 가능한 한 안 씁니다. backend 교체 시 코드 변경 최소.
2. **Langfuse를 trace storage / UI로** — self-host 또는 cloud. OTLP/HTTP 엔드포인트(`/api/public/otel/v1/traces`)로 직접 전송.
3. **OTel Collector 미도입(선택)** — 단일 backend라면 SDK가 직접 송신. 부담을 줄임. 다중 백엔드(예: Langfuse + Tempo 병행)나 attribute 변환이 필요해지면 그때 Collector 추가.
4. **서비스 로직은 ClickHouse 직접 쿼리** — admin 대시보드의 토큰 합산·CSV 다운로드 같은 경로는 Langfuse REST API보다 ClickHouse SQL이 훨씬 빠르고 vendor-independent.

```
┌─ Service Layer (서비스 로직) ────────────────┐
│  - 대시보드 토큰 합산                          │
│  - CSV 다운로드                               │
│  - 사용자별·모델별 통계                        │
└────────────┬────────────────────────────────┘
             │ SQL (Vendor-independent)
             ▼
       ┌──────────────┐
       │ ClickHouse   │←─ Langfuse worker가 적재
       └──────────────┘
             ▲
             │ OTLP/HTTP
       ┌─────┴────────┐
       │ Application  │ — OTel SDK만 사용
       │ (FastAPI)    │
       └──────────────┘
```

### 5.2 단일 진실 공급원 — Dual-write 없음

레거시 trace 시스템과 비교했을 때 가장 큰 운영 이득은 **사용자 input/output을 별도 테이블에 따로 쓰지 않아도 된다**는 점입니다.

OTel span의 `langfuse.observation.input` / `.output` attribute가 그대로 ClickHouse `observations.input` / `.output`에 들어가므로, "trace 메타데이터는 Mongo/RDB에 쓰고 본문은 다른 컬렉션/오브젝트 스토리지에 쓰는" 식의 dual-write·dual-read를 만들지 않아도 됩니다. CSV 다운로드·채팅 로그 복원도 한 SQL.

### 5.3 암호화 옵션

LLM 서비스는 사용자 질문·답변에 PII가 섞이는 게 일상입니다. 두 가지 큰 트랙이 있습니다.

#### 5.3.1 Langfuse Cloud Enterprise — KMS-managed encryption-at-rest

Langfuse Cloud의 Enterprise tier에서는 ClickHouse·MinIO·PostgreSQL을 포함한 데이터 plane 전반에 KMS 기반 encryption-at-rest를 제공합니다. 사용자가 직접 키를 관리할 필요 없이 컴플라이언스 요구를 만족시킬 수 있는 옵션입니다.

#### 5.3.2 OSS Self-host — 옵트아웃, 직접 구현

OSS edition에는 위 기능이 빠져 있어, 자체 암호화 레이어를 얹어야 합니다. 두 패턴이 흔합니다.

**옵션 A — 뷰어 측 decrypt reverse proxy**

```
Browser/admin-front (iframe)
       │
       ▼
 decrypt-proxy (FastAPI)  ← 응답에서 input/output 평문 복호화
       │
       ▼
 langfuse-web (Next.js)   ← 암호문 그대로 응답
       │
       ▼
 ClickHouse (암호문 저장)
```

- 애플리케이션이 OTel emit 직전 PII 필드를 암호화 (AES-256-GCM 등)
- ClickHouse에는 암호문이 저장됨
- 뷰어에 노출되는 시점에만 proxy가 평문으로 변환
- 부가 효과: proxy에서 권한 검증·iframe CSP 헤더 삽입·서비스 계정 로그인을 같이 처리할 수 있어 보안 통제가 모입니다

**옵션 B — 앱 단 마스킹/암호화 (값 단위)**

```python
# 비-LLM 서비스(채팅 메시지 등)는 민감 필드만 값 암호화
SENSITIVE_KEYS = {"question", "text", "message", "pageContent"}

def encrypt_payload(data, keys):
    if isinstance(data, dict):
        return {
            k: crypter.encrypt(v) if k in keys and isinstance(v, str)
               else encrypt_payload(v, keys)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [encrypt_payload(x, keys) for x in data]
    return data
```

- JSON 구조는 보존, 값만 암호화 → metadata는 검색 가능, 본문만 불투명
- LLM 추론 호출처럼 payload 전체가 민감하면 통째로 `crypter.encrypt(json.dumps(...))` 후 단일 base64 blob으로 저장

### 5.4 코드 예제 — Python OTel SDK 통합

다음은 edge API 서비스에 OTel + Langfuse를 붙이는 최소 코드입니다.

```python
# otel_setup.py
import base64
import os
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.processor.baggage import ALLOW_ALL_BAGGAGE_KEYS, BaggageSpanProcessor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator


def setup_otel(app: FastAPI) -> None:
    service_name = os.environ["OTEL_SERVICE_NAME"]
    langfuse_base = os.environ["LANGFUSE_BASE_URL"]
    pk = os.environ["LANGFUSE_PUBLIC_KEY"]
    sk = os.environ["LANGFUSE_SECRET_KEY"]

    # 1) Resource
    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": os.environ.get("ENV", "dev"),
    })

    # 2) Exporter — Langfuse OTLP/HTTP 직접 송신
    auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    exporter = OTLPSpanExporter(
        endpoint=f"{langfuse_base}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}"},
    )

    # 3) Propagator
    set_global_textmap(CompositePropagator([
        TraceContextTextMapPropagator(),
        W3CBaggagePropagator(),
    ]))

    # 4) TracerProvider
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BaggageSpanProcessor(ALLOW_ALL_BAGGAGE_KEYS))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # 5) Auto-instrumentation
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health,healthcheck,/auth",
        exclude_spans=["receive", "send"],
    )
    AioHttpClientInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
```

미들웨어로 Langfuse 1급 메타데이터를 박는 부분입니다.

```python
# otel_middleware.py
import json
from opentelemetry import baggage, trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class LangfuseAttributeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, trace_name: str = None, collect_io: bool = False):
        super().__init__(app)
        self.trace_name = trace_name
        self.collect_io = collect_io

    async def dispatch(self, request: Request, call_next):
        span = trace.get_current_span()
        if not span or not span.is_recording():
            return await call_next(request)

        # Root span에만 trace 이름 부여
        if span.parent is None and self.trace_name:
            span.set_attribute("langfuse.trace.name", self.trace_name)

        # 1급 메타 — 검색·필터 가능
        span.set_attribute("langfuse.observation.metadata.http_path", request.url.path)
        span.set_attribute("langfuse.observation.metadata.http_method", request.method)

        # baggage → 1급 메타 승격
        if (s := baggage.get_baggage("session.id")):
            span.set_attribute("langfuse.observation.metadata.session_id", str(s))
        if (u := baggage.get_baggage("user.id")):
            span.set_attribute("langfuse.observation.metadata.user_id", str(u))

        # Request body 캡처 (옵션)
        input_text = None
        if self.collect_io:
            try:
                body = await request.body()
                input_text = body.decode("utf-8", errors="replace")
            except Exception:
                pass

        response = await call_next(request)

        if self.collect_io and input_text:
            span.set_attribute("langfuse.observation.input", input_text)
            # response body 캡처는 StreamingResponse 처리 등 추가 작업 필요

        return response
```

서빙 호출에 LLM 특화 속성을 enrich하는 wrapper입니다.

```python
# llm_serving_wrapper.py
import json
from opentelemetry import trace
from opentelemetry.trace import SpanKind

tracer = trace.get_tracer("llm.serving")


async def call_llm_with_tracing(model: str, messages: list, *, serving_id: int):
    with tracer.start_as_current_span("llm.completion", kind=SpanKind.CLIENT) as span:
        span.set_attribute("langfuse.observation.type", "generation")
        span.set_attribute("langfuse.observation.metadata.serving_id", str(serving_id))

        # OTel GenAI 표준
        span.set_attribute("gen_ai.request.model", model)

        # 호출
        response = await http_client.post(
            f"http://gateway/serving/{serving_id}/v1/chat/completions",
            json={"model": model, "messages": messages},
        )
        body = response.json()

        # 응답 enrich
        usage = body.get("usage", {})
        span.set_attribute("gen_ai.response.model", body.get("model", model))
        span.set_attribute("gen_ai.usage.input_tokens", int(usage.get("prompt_tokens", 0)))
        span.set_attribute("gen_ai.usage.output_tokens", int(usage.get("completion_tokens", 0)))
        span.set_attribute("langfuse.observation.input", json.dumps(messages))
        span.set_attribute("langfuse.observation.output", json.dumps(body))
        return body
```

### 5.5 코드 예제 — ClickHouse 직접 쿼리

서비스 로직에서 토큰 합산을 Langfuse REST API 대신 ClickHouse SQL로 처리하는 예시입니다. clickhouse-connect 패키지를 씁니다.

```python
# token_aggregator.py
import clickhouse_connect

CH = clickhouse_connect.get_client(
    host="clickhouse",
    port=8123,
    username="default",
    password="...",
    database="default",
)


def aggregate_serving_tokens(
    project_id: str,
    serving_id: int,
    revision_id: int,
    start_iso: str,
    end_iso: str,
) -> dict:
    """특정 LLM 서빙 + 리비전의 기간 토큰·요청 수 합산."""
    sql = """
    SELECT
        count() AS request_count,
        sum(toInt64OrZero(usage_details['input']))  AS input_tokens,
        sum(toInt64OrZero(usage_details['output'])) AS output_tokens,
        sum(toInt64OrZero(usage_details['total']))  AS total_tokens
    FROM observations FINAL
    WHERE project_id = {project_id:String}
      AND type = 'GENERATION'
      AND metadata['service'] = 'serving'
      AND metadata['serving_id'] = {serving_id:String}
      AND metadata['serving_revision_id'] = {revision_id:String}
      AND start_time BETWEEN {start:DateTime64(3)} AND {end:DateTime64(3)}
    """
    row = CH.query(
        sql,
        parameters={
            "project_id": project_id,
            "serving_id": str(serving_id),
            "revision_id": str(revision_id),
            "start": start_iso,
            "end": end_iso,
        },
    ).result_rows[0]
    return {
        "request_count": row[0],
        "input_tokens":  row[1],
        "output_tokens": row[2],
        "total_tokens":  row[3],
    }
```

세션의 모든 trace를 한 번에 가져와 채팅 로그를 복원하는 예시입니다.

```python
def get_session_chat_log(project_id: str, session_id: str) -> list[dict]:
    """한 채팅 세션의 모든 trace를 시간순으로 — root observation의 input/output만 사용."""
    sql = """
    SELECT
        t.id            AS trace_id,
        t.timestamp     AS created_at,
        o.input         AS request_data,
        o.output        AS response_data
    FROM traces FINAL AS t
    LEFT JOIN observations FINAL AS o
        ON o.trace_id = t.id
        AND o.parent_observation_id IS NULL  -- root observation만
    WHERE t.project_id = {project_id:String}
      AND t.session_id = {session_id:String}
      AND t.timestamp >= now() - INTERVAL 30 DAY
    ORDER BY t.timestamp ASC
    """
    rows = CH.query(
        sql,
        parameters={"project_id": project_id, "session_id": session_id},
    ).result_rows
    return [
        {
            "trace_id": r[0],
            "created_at": r[1].isoformat(),
            "request": r[2],
            "response": r[3],
        }
        for r in rows
    ]
```

이 패턴의 핵심은 **서비스 코드가 Langfuse SDK·REST에 의존하지 않는다**는 점입니다. 만약 Langfuse를 Tempo로 바꾸기로 결정한다면, OTel SDK 통합 코드는 한 줄도 안 바뀌고, ClickHouse 쿼리 코드만 Tempo의 trace store(예: 자체 ClickHouse 또는 Loki)에 맞춰 SQL을 다시 짜면 됩니다. 표준 + 직접 쿼리 조합이 갖는 vendor-independence의 실질입니다.

---

## 마무리

이 글에서는 OpenTelemetry의 기본 개념부터 Langfuse·ClickHouse를 활용한 LLM observability 풀스택을 다뤘습니다. 핵심을 요약하면 다음과 같습니다.

- 분산 추적의 표준은 W3C **TraceContext + Baggage**. B3는 레거시 호환 용도로만 병행
- OTel은 API + SDK + OTLP + 자동 계측의 4축으로 구성. **vendor-neutral**이 최대 장점
- Langfuse는 LLM 특화 backend. OTLP 네이티브로 받고, `langfuse.{trace,observation}.metadata.*` prefix로 1급 메타데이터를 박는 게 핵심
- ClickHouse는 Langfuse의 OLAP 엔진이자 직접 쿼리 가능한 standard 인터페이스. `FINAL`·`project_id`·partition pruning·bloom filter on Map 4가지가 쿼리 성능의 절반
- 통합 설계는 **OTel SDK만 코드에 두고 Langfuse는 backend로, 서비스 로직은 ClickHouse 직접 쿼리** 조합이 vendor lock-in을 최소화

LLM 서비스가 모놀리식 API에서 시작해 워크플로우·에이전트·툴 호출 그래프로 진화할수록, 분산 추적은 운영의 중심축이 됩니다. 표준에 묶고 백엔드는 갈아 끼울 수 있게 두는 설계가, 결국 1~2년 단위로 진화하는 LLM 생태계를 가장 안전하게 추적하는 방법이라고 봅니다.
