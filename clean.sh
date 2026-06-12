#!/bin/bash

rm -rf src/ pkg/ && rm -f *.pkg.tar.zst; echo "cleaned $PWD" || echo "failed to clean"; exit 1

