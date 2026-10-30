output "namespace" {
  value = kubernetes_namespace_v1.demo.metadata[0].name
}

output "workload_mode" {
  value = "Fixture viewer only; no live agent, collector, or model is connected."
}
