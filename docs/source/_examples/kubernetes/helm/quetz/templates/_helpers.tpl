{{/* tag::helm-helpers[] */}}
{{- define "quetz.fullname" -}}
{{- if gt (len .Release.Name) 40 -}}
{{- printf "%s-%s" (.Release.Name | trunc 31 | trimSuffix "-") (.Release.Name | sha256sum | trunc 8) -}}
{{- else -}}{{ .Release.Name }}{{- end -}}
{{- end -}}

{{- define "quetz.labels" -}}
app.kubernetes.io/name: quetz
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end -}}

{{- define "quetz.serviceAccount" -}}
{{- if .Values.serviceAccount.create -}}
{{ default (include "quetz.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
{{ required "serviceAccount.name is required when serviceAccount.create=false" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}

{{- define "quetz.claim" -}}
{{ default (printf "%s-data" (include "quetz.fullname" .)) .Values.persistence.existingClaim }}
{{- end -}}

{{- define "quetz.config" -}}
[session]
https_only = true
[oidc]
issuer = {{ .Values.oidc.issuer | toJson }}
client_id = {{ .Values.oidc.clientId | toJson }}
audience = {{ .Values.oidc.audience | toJson }}
roles_claim = {{ .Values.oidc.rolesClaim | toJson }}
owner_role = {{ .Values.oidc.ownerRole | toJson }}
maintainer_role = {{ .Values.oidc.maintainerRole | toJson }}
member_role = {{ .Values.oidc.memberRole | toJson }}
only = true
allow_insecure_http = false
[plugins]
enabled = []
{{- end -}}

{{- define "quetz.pod" -}}
serviceAccountName: {{ include "quetz.serviceAccount" . }}
automountServiceAccountToken: false
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  fsGroup: 10001
  fsGroupChangePolicy: OnRootMismatch
  seccompProfile:
    type: RuntimeDefault
nodeSelector:
  {{- toYaml .Values.nodeSelector | nindent 2 }}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
volumes:
  - name: data
    persistentVolumeClaim:
      claimName: {{ include "quetz.claim" . }}
  - name: config
    configMap:
      name: {{ include "quetz.fullname" . }}-config
  - name: tmp
    emptyDir:
      sizeLimit: 2Gi
terminationGracePeriodSeconds: 60
{{- end -}}

{{- define "quetz.container" -}}
{{- if .Values.image.digest -}}
image: {{ printf "%s@%s" .Values.image.repository .Values.image.digest | quote }}
{{- else -}}
image: {{ printf "%s:%s" .Values.image.repository (default (printf "v%s" .Chart.AppVersion) .Values.image.tag) | quote }}
{{- end }}
imagePullPolicy: {{ .Values.image.pullPolicy }}
env:
  - name: QUETZ_CONFIG_FILE
    value: /etc/quetz/config.toml
  - name: PYTHONDONTWRITEBYTECODE
    value: "1"
  - name: FORWARDED_ALLOW_IPS
    value: {{ .Values.trustedProxyIPs | quote }}
envFrom:
  - secretRef:
      name: {{ .Values.existingSecret }}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: [ALL]
volumeMounts:
  - name: data
    mountPath: /data
  - name: config
    mountPath: /etc/quetz
    readOnly: true
  - name: tmp
    mountPath: /tmp
resources:
  {{- toYaml .Values.resources | nindent 2 }}
{{- end -}}
{{/* end::helm-helpers[] */}}
