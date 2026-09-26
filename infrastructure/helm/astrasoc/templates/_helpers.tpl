{{- define "astrasoc.fullname" -}}
{{- printf "%s" .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}

{{- define "astrasoc.labels" -}}
app.kubernetes.io/part-of: astrasoc
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "astrasoc.tag" -}}
{{- default .Chart.AppVersion .Values.image.tag -}}
{{- end -}}

{{- define "astrasoc.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "astrasoc.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "astrasoc.origin" -}}
{{- printf "https://%s" .Values.ingress.host -}}
{{- end -}}
