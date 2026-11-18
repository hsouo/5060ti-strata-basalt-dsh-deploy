# RTX 5060 Ti Strata / Basalt / DSH Deployment

[中文说明](README_zh-CN.md)

A small collection of my local LLM deployment configurations for **Strata**, **Basalt**, and **DeepSeek Harness (DSH)**.

The setup is built around an **RTX 5060 Ti 16GB + 96GB DDR4** Windows machine and is mainly used to run **Qwen3.8-Flash-Next** with large system-memory expert offloading.

This repository is intended as a practical reference for running large MoE models on a single consumer GPU.

## Hardware & System

| Component | Configuration |
|---|---|
| OS | Windows 11 25H2, Build 26200.8655 |
| GPU | NVIDIA GeForce RTX 5060 Ti 16GB |
| CPU | Intel Q1K3 |
| P-Core | 4.6 GHz all-core |
| E-Core | 3.4 GHz all-core |
| Ring | 3.6 GHz |
| Memory | 96GB DDR4-3200 |
| Memory Timing | 16-20-38, Gear 1 |
| Motherboard | MSI PRO B760M-A DDR4 II |
| Strata Backend | 0.1.59 |
| Basalt | 0.4.1 |

## Repository Contents

```text
.
├── README.md
├── README_zh-CN.md
├── strata启动参数.txt
├── basalt启动参数.txt
├── dsh系统提示词.txt
└── images/
    ├── strata-monitor.png
    └── basalt-monitor.png
```

## Strata

Tested with **Strata backend 0.1.59**.

`strata启动参数.txt` contains the Strata launch configuration currently used for:

- **Model:** Qwen3.8-Flash-Next UD-IQ3_XXS
- **Context:** 512K
- **KV Cache:** INT8
- **Parallel:** 1
- **MTP:** enabled
- **Drafting:** MTP
- **Vision:** CPU
- **YaRN RoPE scaling:** enabled
- **RoPE scale:** 2
- **KV resident:** 20480 MiB
- **Prefill:** 8192
- **Speculative decoding:** `spec=4`
- **spec-min-p:** `0.7`
- **PCIe / expert I/O:** mmap
- **Port:** `18510`

The configuration is designed to keep the GPU close to full VRAM utilization while using system RAM for the remaining MoE experts.

### Strata Monitor

![Strata Monitor](images/strata-monitor.png)

The screenshot above shows an example long-context workload on the RTX 5060 Ti system. It is included as a real-world operating example rather than a controlled benchmark.

## Basalt

Tested with **Basalt 0.4.1**.

`basalt启动参数.txt` contains the Basalt launch configuration currently used for:

- **Model:** Qwen3.8-Flash-Next NVFP4-DQ8
- **Context:** 512K
- **KV Cache:** INT8
- **Parallel:** 1
- **Vision:** CPU
- **Expert cache:** automatic
- **Resident experts:** enabled
- **Resident expert budget:** 56 GiB
- **YaRN RoPE scaling:** enabled
- **RoPE scale:** 2
- **Speculative decoding:** `spec=4`
- **Draft suffix:** disabled
- **Pool workers:** 14
- **Port:** `18511`

Basalt uses a combination of **VRAM, system RAM, and SSD-backed expert storage**, allowing a larger model quantization to run within the 16GB VRAM limit.

### Basalt Monitor

![Basalt Monitor](images/basalt-monitor.png)

This screenshot shows an example Basalt session with experts distributed across VRAM, RAM, and SSD. Performance varies depending on expert-cache hit rate, context reuse, workload, and system state.

## DeepSeek Harness

`dsh系统提示词.txt` contains the custom system prompt I use with **DeepSeek Harness**.

The prompt is designed for long-running coding and autonomous task execution, with emphasis on:

- execution-first behavior;
- continuing work instead of stopping at planning;
- context-window discipline;
- context compression discipline;
- avoiding invented context-usage estimates;
- reducing repetitive reasoning and unnecessary self-reflection;
- evidence-based investigation;
- verifying commands, edits, and test results;
- avoiding premature task completion;
- strict **single-agent execution**;
- completely disabling the use of sub-agents.

The goal is to make long-running DSH sessions more persistent and execution-oriented, especially for coding, debugging, repository inspection, and iterative development.

## Notes

These configurations are tuned for **my specific hardware and workloads**. They should be treated as reference configurations rather than universal optimal settings.

The behavior and optimal parameters may change across different versions of Strata and Basalt. The configurations in this repository were tested with:

```text
Strata backend: 0.1.59
Basalt:         0.4.1
```

Before using them, modify environment-specific values such as:

- model paths;
- Strata / Basalt installation paths;
- Conda paths;
- CPU affinity;
- available RAM and VRAM;
- resident expert budget;
- service ports;
- context length.

Performance may vary significantly with:

- Strata / Basalt version;
- model and quantization format;
- NVIDIA driver / CUDA version;
- CPU frequency;
- memory bandwidth and latency;
- PCIe configuration;
- SSD performance;
- expert-cache hit rate;
- context reuse ratio.

## Purpose

The goal of this repository is simple:

> Provide a working reference for running large MoE models such as Qwen3.8-Flash-Next on a single RTX 5060 Ti 16GB by combining GPU compute with large system-memory expert offloading.

Feel free to use, modify, benchmark, or improve these configurations.