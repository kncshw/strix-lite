<p align="center">
  <a href="https://github.com/kncshw/strix-lite">
    <img src=".github/logo.png" width="150" alt="Strix Lite Logo">
  </a>
</p>

<h1 align="center">Strix Lite</h1>

<h2 align="center">Targeted AI-Powered Penetration Testing</h2>

<div align="center">

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-%235865F2.svg?&logo=discord&logoColor=white)](https://discord.gg/YjKFvEZSdZ)

</div>

<br>

> [!NOTE]
> **Strix Lite** is a simplified, single-agent version of the original [Strix](https://github.com/usestrix/strix). It removes complex multi-agent orchestration in favor of a single, highly-capable autonomous agent optimized for targeted vulnerability verification and exploit development.

---

## 🦉 Overview

Strix Lite is an autonomous AI agent designed to act as a security researcher. It runs code dynamically, identifies potential vulnerabilities, and validates them by creating functional Proof-of-Concepts (PoCs). 

By focusing on a single-agent loop, Strix Lite provides a more direct and transparent testing experience while maintaining the full power of the original Strix toolkit.

**Key Capabilities:**
- 🔧 **Full hacker toolkit** (Proxy, Browser, Terminal, Python)
- ✅ **Real validation** via automated PoC development
- 💻 **Developer-focused** CLI and interactive TUI
- 🔍 **Targeted Scans** for web apps, repositories, and network targets

---

## 🚀 Quick Start (Local Installation)

Local installation using **Poetry** is the only verified method for running Strix Lite.

### 1. Prerequisites
- **Python 3.12+**
- **Poetry**
- **Docker** (must be running for the sandbox environment)
- **LLM API Key** (OpenAI or Anthropic recommended)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/kncshw/strix-lite.git
cd strix-lite

# Install dependencies
poetry install
```

### 3. Configuration

Set up your environment variables (or create a `.env` file):

```bash
# Core Configuration
export STRIX_LLM="openai/gpt-4o"
export LLM_API_KEY="your-api-key-here"

# Optional: Real-time Web Search (via Firecrawl)
export FIRECRAWL_API_KEY="your-firecrawl-key-here"
```

### 4. Run a Scan

```bash
# Scan a web application
poetry run strix --target https://example.com --instruction "Check for SQL injection"

# Analyze a local directory
poetry run strix --target /path/to/project
```

---

## ✨ Features

- **Autonomous Loop**: The agent researches, executes tools, and iterates until a vulnerability is proven or ruled out.
- **Sandboxed Execution**: All security tools and custom scripts run inside a secure Docker container.
- **Integrated HTTP Proxy**: Full visibility and manipulation of web traffic.
- **Browser Automation**: Interacts with complex web apps just like a human tester.
- **Detailed Reporting**: Generates comprehensive Markdown reports with reproduction steps.

---

## 💻 Usage Examples

### Focused Vulnerability Research
```bash
poetry run strix --target https://api.target.com --instruction "Verify if the /user/debug endpoint is vulnerable to RCE"
```

### Repository Analysis
```bash
poetry run strix -t https://github.com/org/repo --instruction "Find and validate any insecure usage of the 'eval()' function"
```

### Headless Mode (CI/CD)
```bash
# Run without TUI, perfect for automation
poetry run strix -n --target https://target.com
```

---

## 🙏 Acknowledgements

Strix Lite is built upon the foundation created by the [Strix](https://github.com/usestrix/strix) team and utilizes incredible open-source projects including [LiteLLM](https://github.com/BerriAI/litellm), [ProjectDiscovery](https://github.com/projectdiscovery), and [Textual](https://github.com/Textualize/textual).

---

> [!WARNING]
> Only test applications you own or have explicit permission to test. You are responsible for using Strix Lite ethically and legally.
