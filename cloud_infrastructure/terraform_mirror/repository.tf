resource "gitlab_project" "spacktainers" {
  name = "spacktainers"
  import_url = "ssh://git@github.com/BlueBrain/spacktainers.git"
  mirror = true
}
