<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Clinical Record Conformance benchmark comparing three documentation generation pipelines">
</p>

<p align="center"><a href="./README.md">English</a> · <strong>中文</strong></p>

一个模型可以把病历写得通过每一条规则，同时凭空编造其中一半——而合规检查分不出这两者。这个基准测量的就是这道缝。

```bash
git clone https://github.com/shenjiayi692-maker/clinical-record-conformance && cd clinical-record-conformance && python3 -m venv .venv && .venv/bin/pip install -qr requirements.txt && .venv/bin/python -m src.evaluate results/final_run.jsonl --report /tmp/report.md && cat /tmp/report.md
```

这条命令从提交的运行日志重新算出公布的那张表。不需要 API key，不联网，不调模型。

这是一次公开的、全合成数据的复现，只问一个很窄的问题：临床文书的约束层到底应该优化什么？在提交的这次运行里，纯 prompt 的自由文本生成拿到了最高的原始合规率 93.3%，但它填满了 12 个源文本中被刻意抹去的字段中的 10 个；Arm C 则把这些缺口报告出来，而不是默默补全。

所以单看原始合规率是错误的头条指标。换成 `conformant_and_grounded`——既通过全部规则、又没有填任何一个受控缺失项——排名反转：C 达到 80.0%，A 跌到 78.3%。Arm C 的重试挽回了 3 个模型抽取或格式错误中的 3 个，以及 11 个源信息缺失中的 0 个。所以校验器真正有用的角色是路由：模型的错误退回给模型，缺失的事实交给人。

配对的输入形态实验是一个零结果。把内容相同的事实重新排序、并插入干扰，并没有稳定地降低合规率；在联合指标上，Arm C 对叙述式输入和碎片式输入都是 70%，而在 14 对源信息完整的样本上两者都是 100%。完整的 C 流水线成本是 A 的 1.9 倍，不过这个差距大部分在只有模板的 B 阶段就已经存在，三条触发重试的记录只比 B 多出 5.1%。

| Arm | 方法 | **合规且有据** | 原始合规率 | 有据记录 | 必填字段填充率 | 无据填充 | 成本 |
|---|---|---:|---:|---:|---:|---:|---:|
| A | 散文式标准，自由文本输出 | **78.3%** | 93.3% | 83.3% | 100.0% | **10 / 12** | $0.1958 |
| B | 严格 JSON 模板，单次尝试 | **76.7%** | 76.7% | 98.3% | 98.3% | **1 / 12** | $0.3525 |
| C | JSON 模板 + 源感知校验循环 | **80.0%** | 81.7% | 98.3% | 98.3% | **1 / 12** | $0.3704 |

<p align="center">
  <img src="./assets/readme/architecture.svg" width="100%" alt="One record through one arm: declared ground truth and provenance-checked rules enter a loop in which the only model call produces text a deterministic validator checks, a source-aware partition decides whether a violation may be retried, and every attempt is appended to a run log the evaluator turns into conformance, grounding, and joint metrics">
</p>

这里的"有据"被刻意限定为受 manifest 控制的缺失项，而不是每一条事实性陈述。结果与失败分析见[完整报告](results/report.md)，来源、语料设计、指标定义、重试策略和日志完整性细节见[方法学](docs/methodology.zh-CN.md)，流水线为什么是这个形状、每个选择付出了什么代价见[设计决策](docs/decisions.zh-CN.md)。

## 跑起来

这是一次离线批处理实验，不是一个服务。提交的报告不需要 API key 就能复现。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m src.evaluate results/final_run.jsonl --report results/report.md
```

要生成一次新的模型运行：

```bash
cp .env.example .env  # 然后填入 OPENAI_API_KEY
.venv/bin/python -m src.generate
```

这条流水线依赖的是 OpenAI 的 HTTP 协议而不是 OpenAI 这个服务,所以 `--base-url`
可以把它指向任何兼容 OpenAI 接口的端点:

```bash
.venv/bin/python -m src.generate --base-url http://localhost:8080/v1 --input-cost 0 --output-cost 0
```

[local-model-serving](https://github.com/shenjiayi692-maker/local-model-serving)
把 Qwen2.5-0.5B 装进容器并暴露成这样一个端点,同时公布了两个后端的对照:
同一套评测程序、同一份语料、代码一行没改,量出商用 API 与自托管 0.5B 模型之间的真实差距。

## 范围

这是一件评测产物，不是临床产品。它没有用户界面、没有 agent 框架、没有向量数据库、没有 EHR 集成、没有部署配置、不含受保护健康信息、不含私有源码、不含任何医院模板。促成这次复现的生产系统用的是 Qwen2.5-7B；公开基准改用 `gpt-4o-2024-08-06`，是为了不要求复核者自行部署本地 7B 推理，而且它评测的是约束层的行为，并不声称模型等价。这些合成规则和结果不得用于任何临床、合规或文书决策。
