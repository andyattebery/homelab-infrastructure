# The Talos cluster's front door: ingress, certificates and DNS (2026-09-27)

The Super6C Talos cluster ([talos/README.md](../../talos/README.md)) is for learning a typical enterprise production stack, Talos aside. Before any service can move onto it ([../docker-01-to-cluster/](../docker-01-to-cluster/README.md)), it needs a front door:
- a LAN address
- a controller that routes requests to services
- certificates
- DNS names

This doc argues each choice against that goal, so the owner could decide. Facts, versions and sources are in [findings.md](findings.md). Whether Istio's mesh would run on this cluster is in [istio-mesh-on-talos.md](istio-mesh-on-talos.md). **[I]** marks inference.

**Status: decided 2026-10-03, built 2026-10-04** ([talos/README.md](../../talos/README.md), "Ingress and certificates"). The owner chose:
- Gateway API
- Istio, as a gateway only
- one wildcard DNS record, written by the network inventory manager
- names under `*.picluster.<domain_name>`, with one wildcard certificate
- Kubernetes 1.36, which meant a rebuild

The weighing below uses `k8s` as the example subdomain; the owner chose `picluster`.

**Recommended:**
- Gateway API
- Istio, as a gateway only
- names under `*.k8s.<domain_name>`, with one wildcard certificate
- one wildcard DNS record
- rebuild on Kubernetes 1.36

**Least friction instead:**
- Gateway API
- Traefik
- the same names
- DSM's Traefik provider for DNS and dashboard tiles
- stay on 1.37

## Settled, whatever is chosen

- **LAN address: MetalLB 0.16.1 in L2 mode, with one address, `192.168.1.188`.**
  - A bare-metal cluster has no cloud load balancer to give a Service an address. MetalLB is the standard substitute.
  - L2 mode answers ARP for the address from one node, so the router needs no configuration. If that node fails, another takes over.
- **Certificates: cert-manager v1.21.2.** It's the de facto standard, and it issues a Gateway's certificates from an annotation on the Gateway.
  - One ClusterIssuer, `letsencrypt`, uses Cloudflare DNS-01 with the token the Docker hosts' Traefik already uses (the owner's choice). DNS-01 needs no inbound access and can issue wildcards.
  - Its propagation check asks public resolvers, not AdGuard. AdGuard caches NXDOMAIN for a fresh challenge record, which was the failure behind the Docker hosts' July 2026 outage.
- **Secrets and the domain:** everything carrying them lives in one `.tpl`, rendered by one `op inject`. The public repo never holds either.

## How the decisions depend on each other

- **API → controller:** NGINX Gateway Fabric and Envoy Gateway implement only Gateway API. Choosing Ingress leaves only Traefik.
- **Names → DNS:** one wildcard DNS record works only when the names sit under a cluster subdomain (decision 4).
- **Version → controller:** Istio 1.31 and Envoy Gateway 1.9 support Kubernetes up to 1.36. The recommended controller assumes the recommended rebuild (decision 5); staying on 1.37 makes it NGINX Gateway Fabric.

## Decision 1: routing API

How a service declares its route: the original `Ingress` resource, or Gateway API's `Gateway` and `HTTPRoute`.

**Ingress**
- One resource per app holds the host, path, backend and TLS secret.
  - Anything beyond that is a controller-specific annotation: redirects, timeouts, header rules, auth.
  - So an Ingress written for one controller rarely works unchanged on another.
- Stable and staying: "The Kubernetes project has no plans to remove Ingress". But it is frozen: it "is no longer being developed, and will have no further changes or updates made to it."
- It's what most existing clusters run [I], so it's what you'd maintain at a job. It's also small enough to learn without a lab.

**Gateway API**
- It splits the job by role:
  - a `GatewayClass` names the controller
  - a `Gateway` holds the listeners, ports and certificates, and belongs to the platform team
  - each app's namespace owns its `HTTPRoute`s, and the Gateway says which namespaces may attach
- Redirects, header changes and traffic splits are in the spec, so routes carry over between controllers.
- It's the Kubernetes project's own recommendation: "The Kubernetes project recommends using Gateway instead of Ingress."
- ingress-nginx ran in "about half of cloud native environments" and retired in March 2026. Announcing that, the project told its users: "Consider migrating to Gateway API, the modern replacement for Ingress."

**Recommendation: Gateway API.**
- It's what clusters are moving to now.
- It's the layer that carries over between controllers and employers.
- Its role split is a small version of the platform-team/app-team division enterprises run on.

**Ingress instead** only if practising what existing clusters run today matters more than what they're moving to. The controller must then be Traefik.

## Decision 2: controller

The controller watches the Gateway API resources and runs the proxy that receives the traffic. With any of the four you write Kubernetes resources, not proxy configuration, so the proxy underneath isn't a reason to pick one. What differs, measured:

- **How much of Gateway API it implements.** From the official v1.6 conformance reports, counting the HTTP profile's 38 extended features:
  - Envoy Gateway v1.9 and Istio 1.31: 36 each.
  - NGINX Gateway Fabric 2.7: 30. It lacks the standard request and backend timeouts and retries; its own ProxySettingsPolicy covers timeouts instead.
  - Traefik v3.7: 19. It lacks the timeouts and retries too, plus CORS, request mirroring, ListenerSets, static Gateway addresses and client-certificate validation. It also skips one core test: a route attached to more than one Gateway.
  - What a controller doesn't implement, you can't practise on it, and that work moves into its own resources instead.
- **How it extends past the spec.**
  - Envoy Gateway and NGINX Gateway Fabric use their own policy resources, attached to a Gateway or route with `targetRefs`. That's Gateway API's policy-attachment pattern.
  - Istio uses its own security resources; an AuthorizationPolicy attaches to a Gateway with `targetRefs`. Rate limiting has no API of its own: it's "implemented using the EnvoyFilter API", which is raw Envoy configuration.
  - Traefik uses Middlewares, which have no `targetRef`; routes reference them.
- **What comes free.**
  - Envoy Gateway: OIDC, JWT, basic and external auth, and API keys; also retries, circuit breakers and rate limits.
  - Istio: JWT validation and authorization policies. A login flow such as OIDC goes through an external authorizer, called with its CUSTOM action [I]. Rate limits go through EnvoyFilter.
  - NGINX Gateway Fabric: basic auth. JWT and OIDC need NGINX Plus, the paid edition.
  - Traefik: basic, digest and forward auth.
- **Default resource requests**, from the charts. Each node has 6.2–6.8 GiB available, so all of them fit.
  - Istio: istiod asks for 500m CPU and 2 GiB, which can be lowered. Each gateway pod asks for 100m and 128 MiB.
  - Envoy Gateway: the controller asks for 100m and 256 MiB, and each Envoy pod for 100m and 512 MiB.
  - NGINX Gateway Fabric and Traefik set none.
- **Kubernetes support.** Istio 1.31 supports 1.32–1.36, and Envoy Gateway 1.9 is tested on 1.33–1.36. NGINX Gateway Fabric and Traefik cover 1.37 as well.
- **Homelab fit.** Only Traefik gets dashboard tiles from DSM today.
- **How widely it's used.** Nothing measures Gateway API controllers' market share. The indicators are rough ones: Docker Hub pulls, GitHub stars, adopters lists.
  - Envoy itself is mainstream. It's the proxy inside Istio, Cilium's Layer 7 features and Contour.
  - Istio is the big one: 38k GitHub stars, and 12.5 billion pulls of its proxy image.
  - Envoy Gateway is young and small: created in 2022, with 3.1k stars, 45 million pulls and 36 self-listed adopters. SAP, Tencent Cloud, Alibaba Cloud and Docker are among them.
  - NGINX Gateway Fabric is smaller still by stars (1.2k). Traefik is big (65k stars, 3.6 billion pulls), mostly from Docker use like yours [I].
  - So at work you'd most likely meet Envoy through Istio, not Envoy Gateway [I].

**Traefik** (chart 41.6.0, Traefik v3.7.13)
- **For:** DSM tiles work today, and it runs as one component.
- **Against:**
  - It implements the least of the standard: 19 of 38.
  - Your Traefik experience is its Docker labels. On Kubernetes, routes are Gateway API resources or Traefik's own CRDs, so little of that carries over.
  - Its Gateway listener ports must be its entrypoint ports, 8000 and 8443, not 80 and 443.
  - Its IngressRoute and Middleware resources are one step away and do more than the spec. That pulls configs off the portable path.

**NGINX Gateway Fabric** (2.7.2)
- **For:**
  - It implements 30 of 38, plus every extended TCP, UDP, TLS and gRPC feature. It's the only one of the four with UDP routes.
  - Its extensions use policy attachment.
  - It supports Kubernetes "1.32+", so either version fits.
- **Against:**
  - Timeouts and retries aren't standard fields here. Timeouts come from its own ProxySettingsPolicy, and retries only through raw NGINX snippets.
  - JWT and OIDC authentication need the paid edition.
  - No dashboard tiles without a new DSM provider type.

**Envoy Gateway** (v1.9.1)
- **For:**
  - It implements 36 of 38, including request timeouts and retries as HTTPRoute fields.
  - Its extensions use policy attachment. The free project covers auth (OIDC, JWT, external), retries, circuit breakers and rate limits, all as first-class resources.
  - It's lighter than Istio by default.
- **Against:**
  - It's tested only up to Kubernetes 1.36, so it needs the rebuild (decision 5).
  - It's young and small next to Istio. The Envoy you'd meet at work is more likely Istio's.
  - There's no service mesh to grow into.
  - No dashboard tiles without a new DSM provider type.

**Istio, as a gateway only** (1.31.1)
- **For:**
  - It's the Envoy stack enterprises actually run. It implements as much of the standard as Envoy Gateway (36 of 38), plus TCP, TLS and gRPC routes.
  - Installed with its `minimal` profile, it's a gateway alone. Each Gateway gets its own Deployment and Service.
    - A `parametersRef` ConfigMap sets replicas, a PodDisruptionBudget and the like.
    - `spec.infrastructure` annotations reach the Service, which is where MetalLB's address request goes.
  - Its gateway pods run non-root. They need only the `net.ipv4.ip_unprivileged_port_start` sysctl, which Talos's baseline Pod Security level allows.
  - It's a path into a service mesh later. Ambient mode adds mutual TLS and identity-based authorization between services, without sidecars. 42% of CNCF's 2024 respondents ran a mesh.
- **Against:**
  - The mesh path is likely but unproven here. The kernel has everything ambient mode needs, built in. But no one has reported Talos with Flannel, and the nftables-only kernel means using Istio's native nftables mode. A test install after the rebuild settles it ([istio-mesh-on-talos.md](istio-mesh-on-talos.md)).
  - Past the spec, it's Istio's own API: Istio auth resources, and EnvoyFilter (raw Envoy configuration) for rate limits.
  - istiod asks for 2 GiB by default, which the values should lower.
  - It's supported only up to Kubernetes 1.36, so it needs the rebuild (decision 5).
  - A minor release ships about every quarter, and each is supported until six weeks after the release two minors later. That's about two upgrades a year, the same pace as Envoy Gateway (1.9 reaches end of life on 2027-02-14).
  - No dashboard tiles without a new DSM provider type.

**Not offered:**
- **ingress-nginx:** retired.
- **Cilium's Gateway API:** it needs Cilium in place of Flannel, which means rebuilding the cluster's networking.

**Recommendation: Istio as a gateway only, with the rebuild on 1.36.**
- It's the Envoy stack you'd meet at work, and it implements as much of the standard as anything here.
- Running it as a gateway only keeps it small now. Ambient mesh is the next thing to learn on the same install, once a test install confirms it on Talos ([istio-mesh-on-talos.md](istio-mesh-on-talos.md)).
- Its rough edges, its own APIs past the spec and EnvoyFilter for rate limits, are what working with Istio is like.

**Envoy Gateway instead** if a service mesh isn't on your path. It implements as much of the standard, it's lighter, and it covers OIDC and rate limits in first-class resources.

**NGINX Gateway Fabric instead** if you stay on 1.37, or need UDP routes.

**Traefik instead** if DSM tiles without new code outweigh the rest. With decision 3's wildcard record, tiles and a single component are all it has left.

## Decision 3: DNS for cluster host names

When a service gets an HTTPRoute for `foo.k8s.<domain_name>`, something must make that name resolve to the Gateway's `192.168.1.188` in AdGuard. Today NIM writes AdGuard's rewrites from the inventory and from DSM.

**One wildcard record** (`*.k8s.<domain_name>` → `192.168.1.188`)
- **For:**
  - One AdGuard rewrite answers every cluster name, now and later. Adding a service needs no DNS work.
  - It's how OpenShift does it: its install requires a wildcard record, `*.apps.<cluster>.<base_domain>`, that points at the ingress load balancer.
  - It works with any controller, puts no credentials in the cluster, and touches nothing else in AdGuard.
  - AdGuard answers an exact rewrite before a wildcard. So a later per-name rewrite, from DSM for example, wins harmlessly, since it points at the same address.
- **Against:**
  - NIM rejects `*` in names (`is_valid_dns_name`), so NIM needs a small change to accept a leading `*.` in a `services:` entry. NIM is your project.
  - A hand-made rewrite in AdGuard would also work, but the repo wouldn't record it. NIM leaves hand-made rewrites alone, and adguardhome-sync copies rewrites to network-02 and -03.
  - A name with no route still resolves, and gets the Gateway's 404 [I].
  - It needs decision 4's cluster subdomain. A wildcard over the main domain would capture every name.

**ExternalDNS → AdGuard** (ExternalDNS v0.23.0, with the webhook provider `muhlba91/external-dns-provider-adguard` v11.2.0)
- **For:**
  - It's a controller that watches HTTPRoutes and writes one record per host name.
  - It's the standard way clusters publish DNS on cloud providers [I]. Its reconcile loop and ownership model are worth learning.
  - It writes custom filtering rules on network-01. adguardhome-sync copies user rules to network-02 and -03 by default.
- **Against:**
  - The provider "takes ownership of all rules matching" its `dnsrewrite` format, because AdGuard rules can't carry a marker. It would delete any hand-made `dnsrewrite` rule in AdGuard's custom rules. The DNS-HA probe is safe: it's a real record in the zone, not an AdGuard rule.
  - NIM keeps its ownership record in the same custom-rules list. AdGuard's API sets that list as a whole [I], so if NIM and ExternalDNS write at the same moment, one can undo the other's change until the next sync.
  - AdGuard admin credentials live in the cluster.
  - With decision 4's names, it would manage names the wildcard record already answers.

**DSM's Traefik provider** (Traefik only)
- **For:** a DSM `Traefik` provider for the cluster, like those for the Docker hosts. NIM makes a rewrite for each route, and the routes show up as dashboard tiles. It exists today.
- **Against:** it works only with Traefik, and it's a homelab mechanism you won't meet elsewhere.

**A new DSM Gateway API provider** (any controller)
- **For:** dashboard tiles and DNS for any controller, from the standard resources.
- **How:**
  - DSM is your C#/.NET project. A new provider type would list the cluster's HTTPRoutes and turn each host name into a service at `pi-cluster-ingress`.
  - It needs a read-only ServiceAccount, with its kubeconfig vaulted onto docker-01 by the docker-01 playbook.
- **Against:** it's work in the DSM repo first.

**Static entries**
- One `services:` line per service in the inventory. Nothing new, but it's a manual step for every service, which the wildcard makes unnecessary.

**Recommendation: one wildcard record.**
- With decision 4's names, it's one record, set once.
- It's OpenShift's pattern for exactly this layout.
- It touches nothing else in AdGuard.

**ExternalDNS instead** only if learning ExternalDNS itself is the point. Check AdGuard's custom rules for `dnsrewrite` rules first, since it would delete them.

**For dashboard tiles,** the DSM Gateway API provider is the follow-up. It works with any DNS choice.

## Decision 4: host names and certificates

Moved services either get names under a cluster subdomain, or keep their `<service>.<domain_name>` names.

**Names under `*.k8s.<domain_name>`, with one wildcard certificate**
- **For:**
  - One HTTPS listener and one certificate cover every service. Adding a service is an HTTPRoute in its own namespace, with no change to the shared Gateway. That's the platform/app split Gateway API is built for, in the same shape as OpenShift's `*.apps`.
  - Migration can run side by side. The docker-01 copy keeps its name while the cluster copy is tested under `.k8s`; then the old copy is switched off.
  - It makes decision 3's single wildcard record possible.
- **Against:**
  - Moved services change URL, which breaks bookmarks and anything else pointing at the old name.
  - The wildcard certificate's key covers every name under `k8s` [I: acceptable on a LAN].

**Keep `<service>.<domain_name>`**
- **For:** old URLs keep working.
- **Against:**
  - Each name needs its own listener and certificate. That means either an edit to the shared Gateway for each service, or a ListenerSet in the service's namespace.
    - ListenerSets are in the v1.6.1 standard install, and cert-manager has supported them since v1.20.
    - They exist because "the `Gateway` resource is a point of contention".
  - Cutover is a DNS switch on the existing name, so there's no side-by-side test under that name.
  - DNS has to be per name: ExternalDNS, DSM or static entries.

**Recommendation: names under `*.k8s.<domain_name>`.** It keeps the Gateway stable, makes DNS a single record, and lets each move be tested before cutover. Keep the old names only if their URLs matter more than those three things.

## Decision 5: Kubernetes version

Stay on 1.37, which the cluster runs now, or rebuild on 1.36 while nothing is on it. Talos 1.14.1 supports 1.32–1.37.

**Stay on 1.37**
- **For:** no work now.
- **Against:**
  - cert-manager 1.21, the newest release, is tested on 1.33–1.36. It runs outside its tested range until a cert-manager release lists 1.37, and so would Istio 1.31 and Envoy Gateway 1.9.
  - It will very likely work, since both use stable APIs [I]. But "very likely works" is not how production clusters are run.
  - The next Kubernetes upgrade to practise is 1.38, months away [I].

**Rebuild on 1.36**
- **For:**
  - Every add-on runs inside its tested range. That's the production norm: move to a Kubernetes version once the add-ons support it [I].
  - It sets up a real upgrade exercise. Once cert-manager supports 1.37, you check each add-on and then run `talosctl upgrade-k8s`. Upgrading a live cluster is a core production skill [I].
- **Cost:**
  - Reset all six nodes, then repeat Build steps 6–9 of [talos/README.md](../../talos/README.md): configs, apply, bootstrap, Longhorn. At worst, add a reflash of the six cards.
  - Nothing runs on the cluster yet, so it will never be cheaper. Later, going back a version would mean rebuilding with data on the cluster.
  - The rebuild steps get written and approved before anything runs.

**Recommendation: rebuild on 1.36.** The goal is production practice, and that practice is running add-ons inside their support range, then upgrading on purpose. It also puts Istio, decision 2's recommendation, inside its supported range, and Envoy Gateway too. Stay on 1.37 only if you'd rather not spend the time now; the controller then becomes NGINX Gateway Fabric.
