Title: (Telepresence OSS 대안) Istio(mTLS) 서비스메시 환경에서 mirrord로 로컬 개발 루프 구성하기
Date: 2026-02-23 17:15
Modified: 2025-02-23 17:15
Tags: Kubernetes, Dev Tool
Author: 박이삭
Category: development
Summary: 로컬개발환경 istio k8s클러스터 연결하는 툴 mirrord

---

이전 글에서 [Telepresence OSS: 로컬 개발환경 Kubernetes Cluster Network에 “붙이는” 방법]({filename}/markdown/telepresence-oss.md)을 정리했습니다. 다만 **Istio(mTLS) 서비스메시 환경**에서는 Telepresence-OSS의 intercept가 안정적으로 동작하지 않는 상황을 여러 번 겪었습니다. 이번 글은 그 원인을 조금 더 구조적으로 분석하고, 같은 환경에서 **mirrord로 전환하는 이유**와 **실사용 튜토리얼**을 정리합니다.

---

## 0. 목표(개발 시나리오)

목표는 단순합니다.

- 로컬에서 FastAPI/uvicorn(또는 uv run)으로 애플리케이션을 실행하면서
- **클러스터 내부 DNS / 내부 서비스 / 메시 정책**을 그대로 적용한 조건에서
- 실제 트래픽을 로컬로 유입(또는 복제)시켜 디버깅과 빠른 반복을 수행한다.

---

## 1. Istio(mTLS)에서 Telepresence intercept가 깨지는 원인 분석

### 1.1 Telepresence intercept의 핵심 동작

Telepresence의 intercept는 **타깃 워크로드의 트래픽을 개발자 워크스테이션(로컬 머신)으로 전송**하는 모델입니다. 공식 문서에서도 intercept 시 “대상 포트로 향하는 TCP/UDP 트래픽이 개발자 워크스테이션으로 전송된다”고 명시합니다. ([Telepresence](https://telepresence.io/docs/reference/engagements/sidecar?utm_source=chatgpt.com))

또한 Microsoft AKS 문서 역시 Telepresence가 워크로드 파드에 Traffic Agent를 주입하고, **인바운드/아웃바운드 트래픽을 로컬 머신으로 재라우팅**한다고 설명합니다. ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/aks/use-telepresence-aks?utm_source=chatgpt.com))

즉, “클러스터 내부 트래픽 경로의 일부가 로컬(클러스터 외부)로 빠지는 구조”가 됩니다.

### 1.2 Istio mTLS의 전제(왜 ‘사이드카’가 중요한가)

Istio의 mTLS(특히 STRICT)는 보통 “워크로드 간 통신이 **각 워크로드의 Envoy 사이드카**를 통해 흐르고, 그 사이드카 간에 mTLS 핸드셰이크가 수행된다”는 전제를 둡니다. 사이드카는 파드 내부 트래픽을 가로채고, 상대 사이드카와 mTLS 연결을 수립합니다. ([Dive Log](https://dive98.blog/posts/istio_mtls_zerotrust/?utm_source=chatgpt.com))

이 관점에서 보면, 트래픽 경로가 **메시 내부(사이드카 존재) → 메시 외부(사이드카 부재)** 로 끊기는 구간이 생기면 다음 문제가 발생하기 쉽습니다.

- **mTLS ID(서비스어카운트 기반) / 정책(AuthorizationPolicy 등) / 암호화 전제**가 성립하지 않는 구간이 생김
- Envoy가 기대하는 형태의 트래픽(예: mTLS로 들어와야 하는 트래픽, 특정 SNI/ALPN/인증서 조건 등)이 어긋나면서 handshake 실패 또는 403/503류 거부가 발생 가능

### 1.3 “intercept된 트래픽이 로컬로 오는 구간”에서 흔히 깨지는 포인트

Telepresence intercept는 트래픽을 로컬로 내려보내지만, **로컬 프로세스는 Istio 사이드카(Envoy)를 갖고 있지 않습니다.** 이 상태에서 메시가 “워크로드 간 mTLS”를 강하게 요구하는 구성이라면, 아래 두 축에서 문제가 재현될 수 있습니다.

1. **트래픽이 Envoy 경로를 ‘정상적으로’ 통과하지 못하는 경우**
    
    Telepresence는 intercept 과정에서 Traffic Agent를 주입/경유시키는데, Istio가 주입한 사이드카와 Telepresence가 주입하는 구성요소(traffic-agent)가 **의도대로 함께 구성되지 않거나**, intercept용 pod/구성이 Istio 환경에서 기대한 형태로 완성되지 않는 이슈가 보고되어 있습니다. 예를 들어 Istio가 있는 환경에서 intercept 시 traffic-agent가 기대대로 붙지 않는 사례가 있습니다. ([GitHub](https://github.com/telepresenceio/telepresence/issues/3558?utm_source=chatgpt.com))
    
2. **메시 밖(로컬)로 빠진 트래픽이 mTLS 전제와 충돌하는 경우**
    
    Telepresence 문서가 설명하는 것처럼 “대상 포트 트래픽이 워크스테이션으로 전송”되는 구조 자체가, 메시 관점에서는 “정책/암호화가 적용되는 경로 밖으로 트래픽이 빠지는 것”입니다. ([Telepresence](https://telepresence.io/docs/reference/engagements/sidecar?utm_source=chatgpt.com))
    
    Istio mTLS는 기본적으로 사이드카 간 mTLS를 전제로 동작하므로, 이 구간에서 **정책/인증/암호화 기대치 불일치**가 누적되면 깨질 확률이 높습니다. ([tetrate.io](https://tetrate.io/blog/how-istios-mtls-traffic-encryption-works-as-part-of-a-zero-trust-security-posture?utm_source=chatgpt.com))
    

> 결론적으로, Telepresence-OSS intercept는 “트래픽을 로컬(메시 외부)로 전송하는 설계” 때문에, Istio(mTLS) STRICT 환경에서는 구조적으로 충돌 가능성이 커집니다.
> 
> 
> (추가로, Telepresence 이슈에서 **OSS는 serviceMesh Helm 값을 지원하지 않는다**는 언급도 있어, 메시 친화적 설정 적용 자체가 제한될 수 있습니다.) ([GitHub](https://github.com/telepresenceio/telepresence/issues/3792?utm_source=chatgpt.com))
> 

이 지점이 제가 mirrord로 전환하게 된 핵심 배경입니다.

---

## 2. mirrord가 Istio(mTLS) 환경에서 유리한 이유(구조 관점)

![image.png](../images/mirrord/image.png)

mirrord는 “로컬 프로세스를 클러스터 컨텍스트에서 실행하는 것처럼 보이게” 만드는 도구인데, 핵심은 **프로세스 레벨에서의 시스템 콜/네트워크 호출 가로채기 + 클러스터 내부 에이전트 실행**입니다.

공식 아키텍처 문서에서 mirrord는 다음을 명확히 말합니다.

- `mirrord-agent`는 쿠버네티스 Job으로 실행되며, **타깃 파드와 동일한 Linux namespace 컨텍스트**에서 동작한다 ([MetalBear](https://metalbear.com/mirrord/docs/reference/architecture?utm_source=chatgpt.com))
- **Outgoing 트래픽은 로컬 프로세스에서 인터셉트되지만, 실제 송신은 agent가 “타깃 파드에서 나가는 것처럼” 방출한다** ([MetalBear](https://metalbear.com/mirrord/docs/reference/architecture?utm_source=chatgpt.com))
- 로컬 프로세스는 `mirrord-layer`를 통해 시스템 호출이 가로채어지고, 원격에서 실행된 결과를 받는다 ([GitHub](https://github.com/metalbear-co/mirrord/blob/main/CLAUDE.md?utm_source=chatgpt.com))

이 구조가 Istio(mTLS)에서 중요한 이유는 간단합니다.

- 트래픽의 “실제 출발점/도착점”이 메시 내부(타깃 파드 컨텍스트)에 유지되면,
- Istio가 기대하는 “사이드카 기반 mTLS 경로”가 더 자연스럽게 유지됩니다. ([tetrate.io](https://tetrate.io/blog/how-istios-mtls-traffic-encryption-works-as-part-of-a-zero-trust-security-posture?utm_source=chatgpt.com))

즉, Telepresence처럼 “트래픽을 로컬(메시 외부)로 내려보내는 구간”이 핵심 경로에 크게 생기지 않는 방향으로 설계되어 있어, 동일한 Istio(mTLS) 환경에서 충돌 가능성이 상대적으로 낮아집니다.

---

## 3. mirrord 내부 동작(Under the hood)

### 3.1 구성요소

- **mirrord CLI**: `mirrord exec ...` 형태로 로컬 프로세스를 실행
- **mirrord-layer(로컬)**: 로컬 프로세스에 주입되어 네트워크/DNS/파일/환경 접근을 가로채는 레이어 ([GitHub](https://github.com/metalbear-co/mirrord/blob/main/CLAUDE.md?utm_source=chatgpt.com))
- **mirrord-agent(클러스터)**: 타깃 파드 컨텍스트에서 네트워크/파일 접근을 대신 수행하고 로컬과 중계 ([MetalBear](https://metalbear.com/mirrord/docs/reference/architecture?utm_source=chatgpt.com))

### 3.2 트래픽 흐름 요약

![image.png](../images/mirrord/image%201.png)

**Outgoing(로컬 → 클러스터 내부 서비스 호출)**

- 로컬 프로세스의 connect/DNS 호출이 layer에서 가로채어짐
- agent가 타깃 파드 컨텍스트에서 실제 연결을 수행
- 결과가 로컬로 반환
    
    (“agent가 타깃 파드에서 나가는 것처럼 트래픽을 방출”한다는 점이 핵심) ([MetalBear](https://metalbear.com/mirrord/docs/reference/architecture?utm_source=chatgpt.com))
    

**Incoming(클러스터 → 로컬로 요청 유입)**

- mirrord는 incoming 모드로 **mirror(복제)** 또는 **steal(가로채기)** 를 제공
- 이 글에서는 실제 로컬 디버깅을 위해 steal을 사용

---

## 4. 튜토리얼: 현재 환경(dev 컨텍스트, llmops 네임스페이스)에 적용

### 4.1 설치(공식 설치 스크립트)

```bash
curl -fsSL https://raw.githubusercontent.com/metalbear-co/mirrord/main/scripts/install.sh | bash
mirrord --version
```

mirrord 소개 문서(공식)도 “로컬 프로세스를 클라우드/스테이징 환경 컨텍스트에서 테스트한다”는 방향으로 정리합니다. ([MetalBear](https://metalbear.com/mirrord/docs/overview/introduction?utm_source=chatgpt.com))

---

## 5. 내 설정 파일 + Makefile로 실행하기

### 5.1 mirrord-config.json

질문에서 제공한 설정을 그대로 사용합니다.

```json
{
  "kube_context": "dev",
  "target": {
    "path": "deployment/llmops-gateway-api-deployment/container/llmops-gateway-api",
    "namespace": "llmops"
  },
  "feature": {
    "network": {
      "incoming": {
        "mode": "steal",
        "port_mapping": [
          [8087, 8080]
        ]
      },
      "outgoing": {
        "ignore_localhost": true
      }
    }
  }
}
```

핵심 포인트:

- `target.path`: 특정 deployment/container를 명시해 “어떤 워크로드 컨텍스트를 impersonate할지”를 고정
- `incoming.mode=steal`: 대상 포트 트래픽을 로컬 프로세스로 유입(가로채기)
- `port_mapping [[8087,8080]]`: 로컬은 8087로 받고(내 로컬 서버 포트), 클러스터 타깃 서비스 포트는 8080을 기준으로 매핑
- `outgoing.ignore_localhost=true`: 로컬에서 localhost로 붙는 호출은 원격 우회하지 않도록(예: 로컬 redis/dev tool 등)

---

### 5.2 Makefile

```makefile
.PHONY: mirrord

mirrord:
	mirrord exec -f mirrord-config.json -- env PROFILE=prod uv run src/main.py
```

실행:

```bash
make mirrord
```

---

## 6. 동작 검증 체크리스트(권장)

1. **클러스터 내부 DNS/서비스 접근이 로컬 프로세스에서 되는지**
- 예: `.svc.cluster.local` 호출이 로컬에서 성공하는지 확인
    
    (이 단계가 되면 “로컬 실행인데 클러스터 내부 컨텍스트로 접근”이 성립)
    
1. **Incoming steal이 실제로 로컬 코드로 들어오는지**
- Ingress/Gateway 경유로 대상 서비스에 요청을 보내고
- 로컬 프로세스 로그/브레이크포인트가 타는지 확인
1. **Istio 관측(Envoy 로그/정책)**
- Envoy가 요청을 거부하는 경우가 있으면 `istio-proxy` 로그를 우선 확인
    
    (Istio 공식 문서도 “거부 원인 파악에 Envoy 로그 확인”을 권장) ([Istio](https://istio.io/latest/docs/ops/common-problems/network-issues/?utm_source=chatgpt.com))
    

---

## 7. 정리: mirrord로 전환하는 이유(telepresence 대비)

- Telepresence intercept는 설계상 **대상 포트 트래픽을 워크스테이션으로 전송**합니다. ([Telepresence](https://telepresence.io/docs/reference/engagements/sidecar?utm_source=chatgpt.com))
- Istio mTLS(특히 STRICT)는 **사이드카 기반 mTLS 경로**를 강하게 전제합니다. ([tetrate.io](https://tetrate.io/blog/how-istios-mtls-traffic-encryption-works-as-part-of-a-zero-trust-security-posture?utm_source=chatgpt.com))
- 이 두 전제가 만나면, “메시 내부 → 로컬(메시 외부)”로 빠지는 구간에서 **인증/정책/암호화 전제 불일치**가 발생하기 쉽고, 실제로 Istio 환경에서 intercept 관련 문제가 보고되어 왔습니다. ([GitHub](https://github.com/telepresenceio/telepresence/issues/3558?utm_source=chatgpt.com))
- 반면 mirrord는 outgoing 트래픽을 **타깃 파드 컨텍스트에서 나가는 것처럼 agent가 방출**하고, agent가 타깃 파드와 동일한 컨텍스트에서 동작하도록 설계되어 있습니다. ([MetalBear](https://metalbear.com/mirrord/docs/reference/architecture?utm_source=chatgpt.com))

따라서 Istio(mTLS) 환경에서 “로컬 디버깅/빠른 반복”을 안정적으로 만들고 싶다면, 제 환경에서는 mirrord가 더 일관된 해법이었습니다.