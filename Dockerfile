FROM runpod/comfyui:1.4.7-cuda13.0@sha256:bad26aad809a442a0d2674827d58c03f95686d0ea6d0d0e0cbebacd787488797
COPY runpod-h3-bootstrap.py /opt/h3-bootstrap.py
COPY validate-image.py /opt/validate-image.py
ENV HF_HUB_ENABLE_HF_TRANSFER=0 HF_XET_HIGH_PERFORMANCE=1 PYTHONUNBUFFERED=1
RUN python3.12 -c "import ast, pathlib, huggingface_hub, torch; ast.parse(pathlib.Path('/opt/h3-bootstrap.py').read_text()); assert pathlib.Path('/opt/comfyui-baked/main.py').is_file()"
ENTRYPOINT ["python3.12", "-u", "/opt/h3-bootstrap.py"]
