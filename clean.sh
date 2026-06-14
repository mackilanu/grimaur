#!/bin/bash
rm -rf grimoire-git/ src/ pkg/ && rm -f *.pkg.tar.zst; echo "cleaned $PWD" || echo "failed to clean"; exit 1

