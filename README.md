# Advanced Relations

A custom [HACS](https://hacs.xyz/) (Home Assistant Community Store) integration for [Home Assistant](https://www.home-assistant.io/), designed to provide improved relationship view of your automations.

## Overview

**Advanced Relations** provides relations visualization between entities, automations, scripts and even templates.
Data is collected by reading automations.yaml, scritps.yaml, core.entity_registry and core.config_entries.


## Features

- Advanced relationship modeling for Home Assistant entities
- Calculated IoT class support
- Compatible with Home Assistant 2025.1.0 and newer

## Installation

1. Ensure you have [HACS](https://hacs.xyz/) installed in your Home Assistant setup.
2. In HACS, add this repository as a custom integration:
    - Go to **HACS > Integrations > Custom repositories**
    - Add `https://github.com/Pave87/advancedrelations` as a custom repository
    - Choose **Integration** as the category
3. Search for **Advanced Relations** in HACS and install it.
4. Restart Home Assistant to complete the setup.

## Configuration

This integration is configured in integrations page in UI. 

## Requirements

- Tested on Home Assistant 2025.6.0 and newer

## Support

For issues and feature requests, please open an issue in this repository.
