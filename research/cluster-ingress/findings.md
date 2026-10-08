# Findings: the cluster's front door

Checked 2026-09-27. Quotes are verbatim. **[I]** marks inference.

## Routing API and controllers

- **Ingress is frozen** (Kubernetes docs, "Ingress"):
  - "The Kubernetes project recommends using Gateway instead of Ingress. The Ingress API has been frozen."
  - It "is no longer being developed, and will have no further changes or updates made to it."
  - "The Kubernetes project has no plans to remove Ingress from Kubernetes."
- **ingress-nginx is retired.**
  - `kubernetes/ingress-nginx` is archived (GitHub API `archived=true`; last push 2026-03-23; last release controller-v1.15.1, 2026-03-19).
  - README: "Best-effort maintenance will continue until March 2026."
  - "Ingress NGINX is used in about half of cloud native environments." (statement of the Kubernetes Steering and Security Response Committees, 2026-01-29)
  - The retirement post (2025-11-11): "We recommend migrating to one of the many alternatives." and "Consider migrating to Gateway API, the modern replacement for Ingress." The fetched text was cut off before its list of alternative Ingress controllers.
- **Traefik:**
  - v3.7.13 (2026-09-04); chart 41.6.0 (2026-09-16, `kubeVersion: >=1.25.0-0`).
  - Gateway API: "This provider supports Standard version v1.6.1 of the Gateway API specification", with a conformance report (Traefik v3.7 docs, `reference/install-configuration/providers/kubernetes/kubernetes-gateway.md`).
  - Listener ports: "`Gateway` listener ports must match the configured EntryPoint ports of the Traefik deployment" (`reference/routing-configuration/kubernetes/gateway-api.md`). In the chart those ports are web 8000 and websecure 8443.
  - Chart defaults (`helm show values … --version 41.6.0`):
    - `providers.kubernetesGateway.enabled: false`, `gateway.enabled: true` (a `web:8000` listener only), GatewayClass named `traefik`
    - `deployment.replicas: 1`, `podDisruptionBudget.enabled: false`, `ingressRoute.dashboard.enabled: false`
  - Its own ACME: "In Traefik Proxy, ACME certificates are stored in a JSON file" (chart `EXAMPLES.md`). On a Longhorn ReadWriteOnce volume, one pod can mount it [I].
- **NGINX Gateway Fabric** 2.7.2 (2026-09-16).
  - Installed with `helm install ngf oci://ghcr.io/nginx/charts/nginx-gateway-fabric --create-namespace -n nginx-gateway` (chart README).
  - Chart values (v2.7.2): `gatewayClassName: nginx`; data plane `nginx.kind: deployment`, `nginx.replicas: 1`; `nginx.service.type: LoadBalancer`, `externalTrafficPolicy: Local`, `loadBalancerIP: ""` ("applied globally to all Gateways").
  - Its README table: Gateway API 1.6.1, Kubernetes "1.32+".
  - Both images are published for amd64 and arm64: the control plane `ghcr.io/nginx/nginx-gateway-fabric:2.7.2` and the data plane `ghcr.io/nginx/nginx-gateway-fabric/nginx:2.7.2`.
- **Envoy Gateway** v1.9.1 (2026-08-28). Its compatibility matrix: v1.9 runs Envoy distroless-v1.39.x and Gateway API v1.6.1 on Kubernetes v1.33–v1.36, with end of life 2027/02/14; the "latest" (development) row lists v1.34–v1.37. `envoyproxy/gateway:v1.9.1` has amd64 and arm64.
- **Gateway API** latest v1.6.2 (2026-09-03); the controllers above declare 1.6.1.
  - The v1.6.1 `standard-install.yaml` defines `listenersets.gateway.networking.k8s.io` (grep of the release asset).
  - GEP-1713 (ListenerSet), status Standard: "The `Gateway` resource is a point of contention since it is the only place to attach listeners with certificates."

## Conformance and extension resources

- **Gateway API v1.6 conformance reports** (`conformance/reports/v1.6/` in `kubernetes-sigs/gateway-api`; experimental channel, default mode, all against Gateway API v1.6.1):
  - Envoy Gateway v1.9.0: HTTP core success, extended 36 supported and 2 unsupported; TLS 10 and 2; gRPC 8 and 2. No TCP or UDP profile.
  - NGINX Gateway Fabric 2.7.0: HTTP core success, extended 30 and 8; TLS 12 and 0; UDP 11 and 0; gRPC 10 and 0; TCP 11 and 0.
  - Traefik v3.7.10: HTTP core partial (36 passed, 1 skipped: `HTTPRouteMultipleGateways`), extended 19 and 19; TLS 3 and 9; gRPC core success, no extended.
  - HTTP extended features where they differ; 17 pass on all three:
    - Envoy Gateway only: `HTTPRouteRequestTimeout`, `HTTPRouteBackendTimeout`, `HTTPRouteRetry`, `HTTPRouteRetryBackendTimeout`, `HTTPRouteRetryConnectionError`, `BackendTLSPolicySANValidation`
    - NGINX Gateway Fabric only: `GatewayHTTPSListenerDetectMisdirectedRequests`, `GatewayInfrastructurePropagation`
    - both of those, not Traefik: `GatewayAddressEmpty`, `GatewayStaticAddresses`, `GatewayHTTPListenerIsolation`, `GatewayBackendClientCertificate`, `GatewayFrontendClientCertificateValidation` (and its `InsecureFallback`), `HTTPRouteCORS`, `HTTPRouteRequestMirror` (and `Multiple`, `Percentage`), `ListenerSet`
    - Envoy Gateway and Traefik, not NGINX Gateway Fabric: `HTTPRouteBackendRequestHeaderModification`, `HTTPRouteNamedRouteRule`
- **Each chart's own CRDs** (`helm show crds`), with the spec fields of the ones compared:
  - NGINX Gateway Fabric 2.7.2:
    - AuthenticationFilter: `basic`, `jwt`, `oidc`, `type`. The schema describes `jwt` and `oidc` as "(NGINX Plus)".
    - ClientSettingsPolicy: `body`, `keepAlive`, `targetRef`.
    - ProxySettingsPolicy: `buffering`, `timeout`, `targetRefs`.
    - UpstreamSettingsPolicy: `hashMethodKey`, `keepAlive`, `loadBalancingMethod`, `useClusterIP`, `zoneSize`, `targetRefs`.
    - Also: RateLimitPolicy, WAFPolicy, SnippetsFilter, SnippetsPolicy, NginxProxy, NginxGateway, PayloadProcessor, ExternalLoadBalancer.
  - Envoy Gateway v1.9.1 (the chart also ships the Gateway API CRDs):
    - SecurityPolicy: `apiKeyAuth`, `authorization`, `basicAuth`, `cors`, `csrf`, `extAuth`, `jwt`, `oidc`, `targetRef(s)`, `targetSelectors`.
    - BackendTrafficPolicy: `retry`, `timeout`, `circuitBreaker`, `rateLimit`, `healthCheck`, `faultInjection`, `loadBalancer` and more, with `targetRef(s)`.
    - ClientTrafficPolicy: `tls`, `http3`, `clientIPDetection`, `timeout` and more, with `targetRef(s)`.
    - Also: EnvoyProxy, EnvoyPatchPolicy, EnvoyExtensionPolicy, Backend, HTTPRouteFilter.
  - Traefik 41.6.0:
    - Middleware: `basicAuth`, `digestAuth`, `forwardAuth`, `rateLimit`, `retry`, `circuitBreaker`, `headers`, `ipAllowList`, `plugin` and more. It has no `targetRef` field.
    - Also: IngressRoute (and TCP, UDP), TraefikService, TLSOption, TLSStore, ServersTransport, and `hub.traefik.io` CRDs for Traefik Hub.

## Adoption

No source found measures Gateway API controllers' market share. What there is, checked 2026-09-28:
- **CNCF surveys:**
  - The 2024 Cloud Native Survey (released 2025-04-01): "Service mesh adoption is declining, dropping from 50% in 2023 to 42% in 2024 due to operational overhead concerns."
  - The 2025 survey (January 2026), as quoted in CNCF's Istio announcement of 2026-03-25: "innovators are nearly three times more likely than explorers to run service mesh in production". The survey PDF was too large to fetch.
- **What runs on Envoy:**
  - Istio: "Istio uses an extended version of the Envoy proxy." (Istio architecture docs)
  - Cilium's proxy: "Envoy with Cilium filters" (`cilium/proxy`)
  - Contour: "a Kubernetes ingress controller using Envoy proxy" (`projectcontour/contour`)
- **Docker Hub all-time pulls** (2026-09-28). Pulls include CI runs and restarts, so they show scale, not deployments.
  - `istio/proxyv2`: 12,482,573,418 (since 2018-05)
  - `envoyproxy/envoy`: 5,768,494,349 (since 2017-11)
  - `library/traefik`: 3,562,359,696 (since 2016-04)
  - `envoyproxy/gateway`: 44,917,009 (since 2022-05)
  - NGINX Gateway Fabric publishes to GHCR, which exposes no comparable count.
- **GitHub** (stars / forks / created):
  - `traefik/traefik`: 64,984 / 6,207 / 2015-09
  - `istio/istio`: 38,410 / 8,375 / 2016-11
  - `envoyproxy/envoy`: 29,007 / 5,634 / 2016-08
  - `kubernetes/ingress-nginx`: 19,459 / 8,558 / 2016-11
  - `envoyproxy/gateway`: 3,054 / 885 / 2022-04
  - `nginx/nginx-gateway-fabric`: 1,169 / 224 / 2021-10
- **Envoy Gateway's adopters page** (`site/data/adopters.yaml`) lists 36 organizations, self-reported. Among them: SAP, Tencent Cloud, Alibaba Cloud, Docker, Canva, Zapier, Procore, The Trade Desk, LY Corporation, OpenAI.

## Istio

- **Releases** (GitHub, 2026-09-28): 1.31.1, 1.30.5 and 1.29.8, all on 2026-09-21.
- **Support policy** (Istio docs, "Supported releases"):
  - "Around once a quarter, we build a minor release". Each is supported "until 6 weeks after the N+2 minor release".
  - 1.31 was released 2026-08-27, with end of life about February 2027. 1.30 was released 2026-05-14, with end of life about December 2026.
  - 1.30 and 1.31 support Kubernetes "1.32, 1.33, 1.34, 1.35, 1.36"; 1.37 isn't listed.
- **Where 1.31 is published** (Istio blog, "retirement of GCP"):
  - Images go "exclusively to `docker.io/istio`".
  - Charts are at `https://blob.istio.io/istio-release/charts` and `ghcr.io/istio/release/charts`.
  - "Istio 1.31 will **not** have Helm charts, OCI Helm charts, nor images published to `gcr.io/istio-release/`, `registry.istio.io/release`, and `https://istio-release.storage.googleapis.com/charts`".
  - Checked: `oci://ghcr.io/istio/release/charts/istiod` has 1.31.1, and the googleapis repo's newest is 1.30.5.
- **Images:** `docker.io/istio/pilot:1.31.1` and `docker.io/istio/proxyv2:1.31.1` are published for amd64 and arm64 (Docker Hub tags API).
- **Install** (Istio docs, Helm): the `base` chart with `--set defaultRevision=default`, then `istiod`. The gateway chart is "(Optional) Install an ingress gateway".
- **Chart defaults** (istiod 1.31.1):
  - istiod `resources` requests 500m CPU and 2048Mi memory.
  - Gateway pods (`global.proxy.resources`) request 100m and 128Mi, with limits of 2000m and 1024Mi.
  - In 1.30.5, `autoscaleEnabled: true` (min 1, max 5).
- **Gateway API mode** (Istio's Gateway API task):
  - It uses `gatewayClassName: istio`, and "a gateway `Deployment` and `Service` is automatically provisioned based on the `Gateway` configuration".
  - `infrastructure` labels and annotations "will be copied onto the generated resources".
  - A `parametersRef` ConfigMap accepts `service`, `deployment`, `serviceAccount`, `horizontalPodAutoscaler` and `podDisruptionBudget`.
  - "A `HorizontalPodAutoscaler` and `PodDisruptionBudget` are not created by default."
- **Pod Security:**
  - The gateway template (`kube-gateway.yaml`, 1.30.5) sets the sysctl `net.ipv4.ip_unprivileged_port_start`, `privileged: false`, `runAsUser` 1337 and `runAsNonRoot: true`.
  - The Pod Security Standards list `net.ipv4.ip_unprivileged_port_start` among the baseline's allowed sysctls.
- **Conformance** (v1.6, Istio 1.31.0): the two unsupported HTTP extended features are `GatewayBackendClientCertificate` and `GatewayHTTPSListenerDetectMisdirectedRequests`. It passes `GatewayStaticAddresses`, `GatewayInfrastructurePropagation` and `ListenerSet`.
- **Policies:**
  - AuthorizationPolicy `targetRefs` supports `kind: Gateway` (`gateway.networking.k8s.io`, same namespace), `GatewayClass` (root namespace), `Service` ("only supported for waypoints") and `ServiceEntry`.
  - The CUSTOM action hands a request to "an extension", from "named providers declared in MeshConfig".
  - Rate limits: "Rate limits as described in this document are implemented using the EnvoyFilter API."
- **Ambient mesh on Talos:** researched separately, with sources, in [istio-mesh-on-talos.md](istio-mesh-on-talos.md).
- **The others' default resources**, for comparison:
  - The Envoy Gateway controller requests 100m and 256Mi (chart).
  - Its Envoy pods request `DefaultDeploymentCPUResourceRequests = "100m"` and `DefaultDeploymentMemoryResourceRequests = "512Mi"` (`api/v1alpha1/shared_types.go`, v1.9.1).
  - The NGINX Gateway Fabric and Traefik charts set no resources.

## cert-manager

- v1.21.2 (2026-09-11). The supported-releases table: 1.21 → Kubernetes 1.33 → 1.36. This cluster runs 1.37, and no newer cert-manager exists.
- Gateway API (docs, "Annotated Gateway resource"):
  - "This feature requires the installation of the Gateway API bundle and passing an additional flag to the cert-manager controller."
  - Helm value `config.gatewayAPI.enabled: true`.
  - "The Gateway API CRDs should either be installed before cert-manager starts or the cert-manager Deployment should be restarted after installing the Gateway API CRDs."
  - The annotations `cert-manager.io/issuer` or `cert-manager.io/cluster-issuer` on a Gateway create its Certificates. ListenerSet support since v1.20.
- Chart values:
  - `crds.enabled` defaults to `false`.
  - `dns01RecursiveNameservers` and `dns01RecursiveNameserversOnly` set the DNS-01 self-check resolvers.
  - `config` defaults `apiVersion`/`kind` when unspecified.

## MetalLB and the cluster network

- MetalLB chart 0.16.1 (2026-05-27, `kubeVersion: >=1.19.0-0`); `frrk8s.enabled: true` by default, the BGP backend, which L2 mode doesn't use.
- MetalLB docs, layer 2 concepts: "In layer 2 mode, one node assumes the responsibility of advertising a service to the local network." "MetalLB responds to ARP requests for IPv4 services". On failure, "failover is automatic: the failed node is detected using memberlist, at which point new nodes take over ownership of the IP addresses from the failed node."
- MetalLB docs:
  - "If you're using kube-proxy in IPVS mode … you have to enable strict ARP mode."
  - Under Pod Security admission the namespace "must be labelled with" enforce/audit/warn `privileged`.
  - CRDs are `metallb.io/v1beta1` (`IPAddressPool`, `L2Advertisement`); a Service picks its address with the annotation `metallb.io/loadBalancerIPs`.
- kube-proxy on this cluster: `mode: nftables` (configmap `kube-proxy-config-*`), so strict ARP doesn't apply.
- `192.168.1.188–190` are free in `network-inventory/network_hosts_inventory.yaml.tpl`.

## Kubernetes version and rebuilds

- Talos v1.14.1 (`pkg/machinery/constants/constants.go`): `DefaultKubernetesVersion = "1.37.0"`, `SupportedKubernetesVersions = 6`, so 1.32–1.37.
- `talosctl reset --help` (1.14.1):
  - `--system-labels-to-wipe`: "if set, just wipe selected system disk partitions by label but keep other partitions intact"
  - `--wipe-mode all, system-disk, user-disks`: "disk reset mode (default all)"
- `talosctl upgrade-k8s --help` (1.14.1): "Command runs upgrade of Kubernetes control plane components between specified versions."

## The OpenShift pattern

- Red Hat's user-provisioned install docs for OpenShift require a wildcard DNS record, `*.apps.<cluster_name>.<base_domain>`, that resolves to the application ingress load balancer (paraphrased; "User-provisioned DNS requirements", OpenShift 4.18 bare metal).

## The homelab's DNS and certificates today

- **The Docker hosts' Traefik** (`ansible/roles/docker_compose_traefik/templates/docker-compose-traefik.yaml.j2`):
  - Resolver `cloudflare`, DNS-01, a certificate per host name.
  - `propagation.requireallrns=false`, with the comment that AdGuard "answers NXDOMAIN and caches it for 1800s (the zone's SOA minimum), which outlives lego's ~2min window".
- **The Cloudflare token and ACME email** the Docker hosts use (`ansible/group_vars/all/vault.yaml.tpl`): `op://Personal/Cloudflare API Token - Ansible Vault DNS Edit/credential` and `op://Personal/Certbot Email/notesPlain`.
- **DSM** (`ansible/files/docker-01/dashboard-services-manager/provider-config.yaml.j2`) discovers services through `YamlFile` and `Traefik` providers, one Traefik provider per host (`TraefikApiUrl`, `Hostname`).
- **NIM** (`network_inventory_manager/sync.py`) builds AdGuard rewrites from:
  - inventory hosts (`<name>.<domain>`)
  - static `services:` entries
  - DSM URLs, pointed at the IP of the provider's `Hostname`

  It has no wildcards: `is_valid_dns_name` rejects `*`, and every inventory name goes through it (`inputs/network_hosts_inventory.py`).
- **How NIM writes AdGuard** (`outputs/adguardhome.py`):
  - Records go through the rewrite API (`/control/rewrite/add`, `/control/rewrite/delete`).
  - Its ownership record is a comment line (`! nim-owned …`) in the custom filtering rules, and it writes the whole list back through `/control/filtering/set_rules`: "Record what NIM owns, preserving every other custom filtering rule."
  - It removes only rewrites it recorded creating (`_types.py`: "Restrict removals to rewrites NIM recorded creating, so hand-made entries …").
- **AdGuard Home's rewrite matching** (`internal/filtering/rewrites.go`, v0.107.79): "The result priority is: CNAME, then A and AAAA; exact, then wildcard.  If the host is matched exactly, wildcard entries aren't returned."
- **adguardhome-sync** v0.9.3 (`nix/pkgs/adguardhome-sync.nix`, configured in `nix/hosts/network-01/default.nix`) copies network-01's AdGuard (origin) to network-02 and -03 (replicas).
  - Its README: "By default, all features are enabled", among them "Sync DNS rewrites" and "Sync user rules". The nix config sets no `features`.
- **The DNS-HA probe** (`nix/modules/network.nix`): "dns-probe.<domain_name> is an A record in our own zone (127.0.0.1, TTL 60)", and "it must NOT be in network-inventory/network_hosts_inventory.yaml.tpl".
- **DSM's code** is the owner's project (`/Users/andy/Projects/dashboard-services-manager`, C#/.NET).
  - Provider types (`src/Dsm.Providers/Options/ServicesProviderType.cs`): `Docker`, `Swarm`, `YamlFile`, `Traefik`.
  - Each implements `IServicesProvider.ListServices()`, returning `Service` records (name, url, image, hostname).
  - `ServicesProviderFactory` and `ProviderOptionsValidator` switch on the type, so a new type means a provider class plus a case in each.
  - The Traefik provider parses routers' `Host(...)` rules into URLs and stamps the configured `Hostname`.
- **ExternalDNS** v0.23.0 (2026-09-18). **The AdGuard webhook provider** `muhlba91/external-dns-provider-adguard` v11.2.0 (2026-09-20) is active: not archived, last push 2026-09-25. Its README (v11.2.0):
  - "The provider manages Adguard Home filtering rules", one rule per record in AdGuard's `dnsrewrite` syntax.
  - "This provider takes **ownership** of **all rules** matching above mentioned format!"
  - "Adguard does not support inline comments for filtering rules, making it impossible to filter out only rules set by External DNS."
  - "rules **not matching** above format, for example, `|domain.to.block`, **will not be modified**."
