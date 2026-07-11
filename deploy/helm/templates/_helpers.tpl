{{- define "appt.commonEnv" -}}
- name: FAKE_PROVIDERS
  value: "{{ .Values.fakeProviders }}"
- name: MCP_RESOURCE_DETAILS_URL
  value: "{{ .Values.env.MCP_RESOURCE_DETAILS_URL }}"
- name: MCP_CALENDAR_URL
  value: "{{ .Values.env.MCP_CALENDAR_URL }}"
- name: MCP_EMAIL_URL
  value: "{{ .Values.env.MCP_EMAIL_URL }}"
- name: SERVICE_BUS_QUEUE_NAME
  value: "{{ .Values.env.SERVICE_BUS_QUEUE_NAME }}"
- name: PUBLIC_BASE_URL
  value: "{{ .Values.env.PUBLIC_BASE_URL }}"
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secretName }}
      key: DATABASE_URL
- name: SERVICE_BUS_CONNECTION_STRING
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secretName }}
      key: SERVICE_BUS_CONNECTION_STRING
- name: MCP_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secretName }}
      key: MCP_API_KEY
{{- end -}}