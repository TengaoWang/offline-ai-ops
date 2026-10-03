# finetune：Qwen3-8B 技能路由微调（T1）

让模型根据用户对故障的描述，选出要执行的技能包：

| 用户说 | 输出 |
|---|---|
| MES 连不上数据库了，网关能 ping 通 | `{"skill": "net-unreachable"}` |
| df -h 看到 /var 用了 98% | `{"skill": "disk-full"}` |
| nginx 起不来 | `{"skill": "service-down"}` |
| 帮我看看最近有没有异常登录 | `{"skill": "log-audit"}` |
| 打印机卡纸了 | `{"skill": null}` |

## 环境（macOS / Apple Silicon）

```bash
uv venv finetune/.venv --python 3.12
uv pip install --python finetune/.venv/bin/python mlx-lm
source finetune/.venv/bin/activate
```

## 流程

```bash
# 1. 生成数据（按说法模板划分，测试集里的说法训练时没见过）
python finetune/gen_data.py

# 2. 基线：未微调的模型
python finetune/eval.py --tag base

# 3. 训练（QLoRA，16GB 内存的 MacBook Air 可跑）
mlx_lm.lora -c finetune/lora_config.yaml

# 4. 微调后评测，与基线对比
python finetune/eval.py --adapter finetune/adapters/qwen3-8b-t1 --tag lora
```

结果保存在 `finetune/results/<tag>.json`。

## 判断标准

- 基线准确率已经 ≥ 90%：不需要微调，直接用基座模型加 `gen_data.py` 里的系统提示词。
- 微调后准确率明显高于基线，且「打印机卡纸」这类无关问题仍能正确输出 `null`：采用微调后的模型。

## 注意

- 训练和推理必须使用同一份系统提示词（`gen_data.py` 中的 `SYSTEM_PROMPT`），并且都使用非思考模式（`enable_thinking=False`）。
- 模型权重、adapter、生成的数据不进 git（见 `.gitignore`）；只提交脚本和配置。
