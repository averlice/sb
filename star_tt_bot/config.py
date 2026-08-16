#!/usr/bin/env python3
"""Configuration for the STAR TeamTalk bot - loads from config.json"""
import os
import json


_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_HERE, "config.json")


def load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()