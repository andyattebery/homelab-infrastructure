# The cluster's Gateway, its certificate issuer and the HTTP-to-HTTPS redirect, with the domain and
# the Cloudflare token as 1Password references. scripts/ingress.sh renders it with one op inject.
apiVersion: v1
kind: Secret
metadata:
  name: cloudflare-api-token
  namespace: cert-manager
type: Opaque
stringData:
  api-token: "{{ op://Personal/Cloudflare API Token - Ansible Vault DNS Edit/credential }}"
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: "{{ op://Personal/Certbot Email/notesPlain }}"
    privateKeySecretRef:
      name: letsencrypt-account-key
    solvers:
      - dns01:
          cloudflare:
            apiTokenSecretRef:
              name: cloudflare-api-token
              key: api-token
---
# Istio patches these into the Deployment and the PodDisruptionBudget it generates for the Gateway
# (strategic merge; it creates the PDB only because the key is here). The label is the one Istio
# puts on every gateway pod, and selects on.
apiVersion: v1
kind: ConfigMap
metadata:
  name: pi-cluster-gateway
  namespace: istio-ingress
data:
  deployment: |
    spec:
      replicas: 2
      template:
        spec:
          topologySpreadConstraints:
            - maxSkew: 1
              topologyKey: kubernetes.io/hostname
              whenUnsatisfiable: DoNotSchedule
              labelSelector:
                matchLabels:
                  gateway.networking.k8s.io/gateway-name: pi-cluster
  podDisruptionBudget: |
    spec:
      minAvailable: 1
---
# Istio generates the Deployment and LoadBalancer Service pi-cluster-istio from this. The
# infrastructure annotation reaches the Service: MetalLB's address request. cert-manager issues
# wildcard-picluster-tls for the https listener's hostname (the metadata annotation).
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: pi-cluster
  namespace: istio-ingress
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
spec:
  gatewayClassName: istio
  infrastructure:
    annotations:
      metallb.io/loadBalancerIPs: 192.168.1.188
    parametersRef:
      group: ""
      kind: ConfigMap
      name: pi-cluster-gateway
  listeners:
    - name: http
      protocol: HTTP
      port: 80
      allowedRoutes:
        namespaces:
          from: Same
    - name: https
      protocol: HTTPS
      port: 443
      hostname: "*.picluster.{{ op://Home Lab/Home Lab/domains/internal }}"
      tls:
        mode: Terminate
        certificateRefs:
          - name: wildcard-picluster-tls
      allowedRoutes:
        namespaces:
          from: All
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: https-redirect
  namespace: istio-ingress
spec:
  parentRefs:
    - name: pi-cluster
      sectionName: http
  rules:
    - filters:
        - type: RequestRedirect
          requestRedirect:
            scheme: https
            statusCode: 301
