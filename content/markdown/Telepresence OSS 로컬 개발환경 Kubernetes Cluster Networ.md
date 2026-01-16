Title: Telepresence OSS: 로컬 개발환경 Kubernetes Cluster Network에 “붙이는” 방법
Date: 2026-01-15 19:01
Tags: kubernetes, k8s, dns, tunnel, remote access, vpn
Author: 박이삭
Category: devops
Summary: 로컬개발환경 k8s클러스터 연결하는 툴 Telepresence

---

## 전제 조건과 환경 가정

이 글은 **Telepresence OSS** 기준으로 작성합니다. 개발 머신(macOS)은 **VPN**을 통해 IDC 내부망에 접근 가능하고, 그 결과로 Kubernetes **API server endpoint**(kubeconfig context)에 접근 가능하다고 가정합니다. Telepresence는 “node에 직접 SSH”하는 모델이 아니라, 기본적으로 **Kubernetes API (port-forward)** 기반으로 클러스터와 데이터를 터널링하는 구성이라서, 네트워크 관점에서 “API 접근 가능성”이 가장 중요합니다. ([telepresence.io](https://telepresence.io/docs/reference/cluster-config))

---

![image.png](../images/telepresence/image.png)

## 1) Introduction to Telepresence

Telepresence는 로컬에서 실행 중인 개발 프로세스를 원격 Kubernetes 클러스터의 네트워크/서비스 디스커버리와 결합해서, **로컬 코드가 마치 클러스터 내부에서 실행되는 것처럼** 동작하게 만드는 도구입니다. CNCF에 2018-05-15에 **Sandbox**로 받아들여졌고, CNCF 페이지에서는 프로젝트 health 및 GitHub stars 같은 지표를 함께 제공합니다. ([CNCF](https://www.cncf.io/projects/telepresence/)) Telepresence OSS GitHub stars는 작성 시점 기준 약 **7.1k** 수준입니다. ([GitHub](https://github.com/telepresenceio/telepresence)) Telepresence는 사이트에서 case studies도 별도로 제공하므로, “실사용 조직/사례”를 공식 채널에서 추적할 수 있습니다. ([telepresence.io](https://telepresence.io/case-studies))

![image.png](../images/telepresence/image%201.png)

### Popularity / Activity 비교 (OSS 중심)

아래 수치는 “작성 시점 GitHub UI에 노출된 값” 기준이며 변동 가능합니다.

- **Telepresence (telepresenceio/telepresence)**: Star **7.1k**, Issues **27** ([GitHub](https://github.com/telepresenceio/telepresence))
- **mirrord (metalbear-co/mirrord)**: Star **4.8k**, Issues **181** ([GitHub](https://github.com/metalbear-co/mirrord))
- **kt-connect (alibaba/kt-connect)**: Star **1.6k**, Issues **104** ([GitHub](https://github.com/alibaba/kt-connect/blob/master/docs/en-us/cli/connect.md))
- **kubevpn (kubenetworks/kubevpn)**: Star **1.3k**, Issues **0** ([GitHub](https://github.com/kubenetworks/kubevpn))

Telepresence 릴리즈는 GitHub Releases 상에서 **v2.25.2 (Dec 26)**가 “Latest”로 표시되고, 동시에 다수의 test/pre-release가 병행되는 형태를 확인할 수 있습니다. ([GitHub](https://github.com/telepresenceio/telepresence/releases))

---

## 2) What it does

### Cluster DNS Resolution from local host

Telepresence는 로컬 DNS resolver를 제공하고, Traffic Manager가 관리하는 namespace 범위에 대해 서비스 이름을 동적으로 resolve합니다. 로컬 프로세스는 연결된 namespace에서는 `service-name`만으로, 그 외 관리 대상 namespace에서는 `service-name.namespace` 형태로 서비스에 접근할 수 있습니다. ([telepresence.io](https://telepresence.io/docs/reference/dns))

### ClusterIP / Pod IP access from local host

Telepresence는 connect 시 **VIF(virtual network interface)**를 만들고, cluster의 **service subnet / pod subnet**으로 라우팅을 구성해서 로컬에서 ClusterIP/Pod IP 대역으로 통신이 가능해집니다. ([telepresence.io](https://telepresence.io/docs/reference/vpn))

### Remote pod traffic intercept → reroute to local machine

Telepresence의 핵심 기능 중 하나는 **intercept**로, 특정 workload(뒤에 service가 매핑된 경우가 일반적)의 트래픽을 로컬로 돌려서 “클러스터에서 들어오는 요청이 로컬 프로세스로 들어오게” 만듭니다. 이때 “해당 서비스로 바인딩되는 트래픽 전체”가 대상이므로, **Ingress로 들어오는 트래픽도 포함될 수 있고**, production에서는 금지 또는 강한 격리 정책이 권장됩니다. ([telepresence.io](https://telepresence.io/docs/2.19/reference/intercepts/cli?utm_source=chatgpt.com))

---

## 3) Architecture

Telepresence는 크게 **local side(daemon)**과 **cluster side(Traffic Manager / Traffic Agent)**로 나뉩니다. cluster side의 Traffic Manager는 클러스터 내부에서 세션/라우팅/DNS/에이전트 관리를 담당하고, 필요 시 Traffic Agent가 대상 workload 쪽으로 붙어서 intercept 경로의 데이터 플레인을 구성합니다. gRPC 기반 터널을 통해 “클러스터 ↔ 로컬” 트래픽이 오갑니다. ([telepresence.io](https://telepresence.io/docs/reference/cluster-config))

![TP_Architecture-4a754cc82947915d1f44ee582315e885.svg](../images/telepresence/TP_Architecture-4a754cc82947915d1f44ee582315e885.svg)

---

## 4) How to? (macOS 튜토리얼)

### 4.1 Install (client / Traffic Manager)

Telepresence OSS는 brew formula로 설치할 수 있습니다. ([telepresence.io](https://telepresence.io/docs/release-notes?utm_source=chatgpt.com)) Traffic Manager는 `telepresence helm install`로 클러스터에 설치하며, Helm value를 통해 일부 cluster-side 설정도 주입할 수 있습니다. ([telepresence.io](https://telepresence.io/docs/reference/cluster-config))

```bash
# (macOS) client install (OSS)
brew install telepresenceio/telepresence/telepresence-oss

telepresence version

```

```bash
# cluster-side install (Traffic Manager)
# (kubeconfig context가 이미 설정되어 있다고 가정)
telepresence helm install

```

예상 결과(예시): `ambassador` namespace(기본값 구성에 따라 다를 수 있음)에 traffic-manager가 배포되고, 이후 client가 connect 시 해당 manager로 연결합니다.

---

### 4.2 Connect (기본 연결 + 검증)

`telepresence connect --namespace <ns>`로 연결하면, 로컬 DNS resolver가 “현재 Traffic Manager가 관리 중인 namespace 집합” 기반으로 동작합니다. ([telepresence.io](https://telepresence.io/docs/reference/dns))

```bash
# ~/.kube/config 기본 context, namespace
telepresence connect

# ~/.kube/config 기본 context와 namespace 지정
telepresence connect --namespace default

```

예시 출력(문서 예제):

```
Connecting to traffic manager...
Connected to context default, namespace default (https://<cluster-public-IP>)

```

연결 후에는 `curl web-app:80` 같은 “cluster service-name 기반 접근”이 로컬에서 가능해집니다. ([telepresence.io](https://telepresence.io/docs/reference/dns))

```bash
curl web-app:80

```

---

### 4.3 Intercept (remote pod 트래픽을 로컬로)

Intercept는 “클러스터로 들어오는 요청을 로컬 프로세스로 전환”하는 기능입니다. `--port 8080:80`처럼 local:remote 포트를 매핑해서, 클러스터가 원래 보내던 트래픽을 로컬의 `:8080`으로 받게 구성합니다. ([telepresence.io](https://telepresence.io/docs/reference/cluster-config))

```bash
# 1) 로컬에서 서비스 실행 (예: 8080 listen)
python -m http.server 8080

```

```bash
# 2) intercept (예: "web-app" workload를 대상으로)
telepresence intercept web-app --port 8080:80

```

주의: Intercept는 “해당 서비스로 바인딩되는 트래픽 전체”가 대상이므로, Ingress를 통해 들어오는 트래픽도 포함될 수 있습니다. production에서는 금지 또는 강한 격리가 권장됩니다. ([telepresence.io](https://telepresence.io/docs/2.19/reference/intercepts/cli?utm_source=chatgpt.com))

---

## 5) 어떻게 하는지? (Under the hood)

### 5.1 Client daemon: VIF(TUN) 데이터 플레인

Telepresence는 로컬에 `tel0` 같은 virtual network interface를 만들고, 해당 인터페이스로 라우팅되는 패킷을 가로채서 “클러스터로 전달할 연결”로 변환합니다. 이 인터페이스는 라우팅/포워딩 관점에서 로컬 프로세스가 ClusterIP/PodIP로 직접 접근하는 것처럼 보이게 해주고, Telepresence 내부 “router”가 TCP/UDP payload를 추출해서 클러스터로 터널링합니다. 공식 문서/README는 이 트래픽이 Traffic Manager의 encrypted gRPC API를 통해 터널링된다고 설명합니다. ([telepresence.io](https://telepresence.io/docs/reference/architecture))

### CIDRs (service/pod subnet)

Telepresence는 connect 과정에서 cluster의 service subnet과 pod subnet을 알아내고, 그 대역을 VIF 라우팅 대상으로 구성합니다. VPN과의 CIDR overlap이 있으면 deterministic하게 해결해야 하며, Telepresence는 기본적으로 VNAT 같은 방식으로 충돌을 회피하도록 설계되어 있습니다. ([telepresence.io](https://telepresence.io/docs/reference/vpn))

---

### 5.2 Local DNS resolver: OS hook + cluster side lookup

Telepresence는 “어떤 이름을 클러스터에서 resolve할지”를 선택적으로 결정하고, 그 lookups를 cluster side로 전파합니다. 기본 선택에는 `.cluster.local` 및 mapped namespace 관련 suffix가 포함되며, 필요 시 include-suffix/mappings로 확장합니다. ([telepresence.io](https://telepresence.io/docs/reference/routing))

macOS에서는 `/etc/resolver` 아래에 파일을 생성하는 방식으로 OS DNS 시스템에 hook하며, 각 파일은 특정 domain과 Telepresence resolver의 port를 포함합니다. 또한 `telepresence.local` 파일은 현재 connect된 namespace 기반의 search path를 구성해서 single-label name(`service-name`)도 올바르게 resolve되게 합니다. ([telepresence.io](https://telepresence.io/docs/reference/routing))

cluster side DNS lookup은 “connected namespace에 agent가 있으면 agent”, 없으면 traffic-manager가 수행합니다. ([telepresence.io](https://telepresence.io/docs/reference/routing))

---

### 5.3 Cluster side: Traffic Manager / Traffic Agent, 그리고 “gRPC over port-forward”

Telepresence 문서는 **“클러스터로 들어가고 나오는 모든 트래픽이 Kubernetes port-forward 위에서 gRPC로 터널링된다”**고 명시합니다. 또한 traffic-manager와 traffic-agent 모두 gRPC server를 제공하고, client가 여기에 연결한다고 설명합니다. ([telepresence.io](https://telepresence.io/docs/reference/cluster-config))

### (중요) Client host → VIF → kubeapi(port-forward) → gRPC API(Traffic Manager) 트래픽 흐름

로컬 프로세스가 ClusterIP/PodIP로 TCP/UDP를 시도하면, 해당 목적지는 VIF(tel0) 라우팅 대상이므로 패킷이 VIF로 흘러갑니다. Telepresence의 router는 패킷을 인지하고, TCP/UDP payload를 추출해 **Traffic Manager로 전달할 스트림**으로 변환합니다. 이때 “클러스터까지의 경로”는 일반적으로 Kubernetes API의 **port-forward 채널**을 통해 형성되고, 그 위에서 gRPC 터널이 동작합니다. ([telepresence.io](https://telepresence.io/docs/reference/architecture))

### Traffic Agent의 역할 (intercept 관점)

Traffic Agent는 **intercept 대상으로 지정된 workload의 Pod에만** sidecar로 주입되는 컴포넌트이며, “클러스터 전체 Pod에 깔리는 형태”가 아닙니다. Telepresence는 첫 intercept 시 workload를 변경해서 해당 workload의 Pod들에 agent 컨테이너가 포함되도록 하고, 이후 그 Pod들이 **Service의 endpoint**로 선택되는 구조를 그대로 이용해 “해당 Service로 들어오는 트래픽”을 Pod 단에서 다룰 수 있게 만듭니다.  Intercept가 활성화되면, Service로 유입된 트래픽이 결국 도달하는 Pod에서 **traffic-agent가 그 트래픽을 받아** gRPC 스트림으로 클러스터 내부의 traffic-manager에 전달하고, traffic-manager가 워크스테이션 쪽으로 프록시합니다. 이때 “서비스 바운드 트래픽”에는 ingress-controller를 통해 들어오는 트래픽도 포함될 수 있으므로, production에서는 금지/격리 정책을 두는 것이 안전합니다. 

---

## 6) 결말: Who and why you should use this

Telepresence는 “로컬 개발 생산성”을 극대화하면서도, 원격 클러스터의 DNS/Service discovery/네트워크 정책 하에서 실제에 가까운 통합 동작을 검증하려는 팀에 적합합니다. 특히 multi-service 환경에서 특정 서비스만 로컬로 띄우고 나머지는 클러스터에 둔 채로 end-to-end 경로를 유지하려는 경우, VIF 기반 라우팅과 DNS Resolution이 강력한 편의성을 제공합니다. 반대로 intercept는 설계상 강력한 만큼 blast radius가 커질 수 있으므로, production에서는 명시적으로 금지하거나 별도 격리된 dev/stage 환경에서만 허용하는 운영 정책이 필요합니다. ([telepresence.io](https://telepresence.io/docs/2.19/reference/intercepts/cli?utm_source=chatgpt.com))