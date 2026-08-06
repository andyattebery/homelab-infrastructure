# docker_compose_kohya_ss

Deploys [kohya_ss](https://github.com/bmaltais/kohya_ss), a GUI for training LoRA and
fine-tuned diffusion models, plus a TensorBoard sidecar reading its training logs.

## Status: Production

## Inputs

- `kohya_ss_image` — default `ghcr.io/bmaltais/kohya-ss-gui:v25.2.2`. **Pinned, not
  floating**: `:latest` moved to v26.0.0 (2026-07-09), whose GUI refactor makes Gradio's
  `url_ok()` startup self-check time out, crash-looping the container.
- `kohya_ss_models_path` — default `<data_dir>/kohya-ss/models`. Host path mounted at
  `/app/models`. Point it at another app's model store to share one download; the role
  creates the directory either way.

## Example

```yaml
- role: docker_compose_kohya_ss
  vars:
    # Share ComfyUI's model store rather than keeping a second copy.
    kohya_ss_models_path: "{{ docker_compose_dst_data_directory_path }}/comfyui/models"
  tags: kohya_ss
```

## `should_pull` is off

The bundled `tensorboard` service is `build:`-only, and `docker_compose`'s pull step loops
over every service from `config --services`. Turning the pull off avoids that.

The cost is that `kohya-ss`'s own image is no longer pulled on every run — which is fine
here: the tag is pinned, so there is no floating tag to keep fresh, and `up --build` fetches
it if it is missing.

## GPU contention

This role and ComfyUI/SwarmUI both want the whole GPU. On a single-GPU host, enable one at a
time rather than expecting them to share.
