#!/bin/bash

test -f .venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Virtual env not found at .venv"
    echo "Create one with uv venv"
    exit 1
fi

source .venv/bin/activate
uv pip install --reinstall .[ocr,search,webui]

echo "Removing generated config"
rm ~/.config/flashback/config.yaml
flashback $@
