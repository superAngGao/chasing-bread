# Chasing Bread

An AI application that generates food recipes — including instructions, flavor profiles, ingredients, and predicted rendering pictures of the final dish.

## Current Focus

The initial phase targets **cake and drink categories**, as their visual presentation is more selective and deterministic compared to other foods. The primary goal right now is generating realistic **rendering pictures** of recipes.

## Architecture

The project is built in Python and consists of the following core components:

### Data Collection Module

Collects recipe-related data (images, descriptions, ingredients, etc.) from public networks and open datasets.

### Data Preprocessing & Filtering

A lightweight AI module that filters collected data for relevance and quality, then preprocesses it into formats suitable for model training.

### Core Model Training

The central component that fine-tunes and trains the main generative AI model for recipe rendering and generation.

### Test Utilities

Supporting scripts and tools for evaluation, debugging, and experimentation — can take any form as needed.

## Tech Stack

- **Language:** Python
- **Domain:** Generative AI, image synthesis, recipe generation

## Roadmap

1. Build data collection pipeline for cake/drink images and recipes
2. Implement preprocessing and filtering module
3. Train and fine-tune the core image generation model
4. Expand to full recipe generation (instructions, tastes, ingredients)
5. Extend beyond cakes/drinks to broader food categories
