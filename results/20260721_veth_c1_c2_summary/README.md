# veth / C1 / C2 × SP有効・無効 比較サマリ（日本語版・英語版）

DiffServ-TE（HTB Strict Priority + WRR）の設計則を、シミュレーション(veth)と
実機テストベッド(C2)で検証した比較成果物。**日本語版と英語版の2つを用意**している。

## フォルダ構成

```
20260721_veth_c1_c2_summary/
├── README.md          ← このファイル(全体の入口)
├── ja/                ← 日本語版(論文・国内向け)
│   ├── plot_sp_ablation.py          生成スクリプト
│   ├── veth_c1_c2_comparison_table.md  6条件の統合数値表
│   ├── README.md                    日本語版の図の説明
│   └── fig_*.png / fig_*.pdf        図16種(各png/pdf)
└── en/                ← 英語版(国際学会プレゼン向け)
    ├── plot_sp_ablation_en.py       生成スクリプト(英語ラベル・大きめフォント)
    ├── README.md                    英語版の図の説明
    └── fig_*.png / fig_*.pdf        図16種(各png/pdf)
```

## 使い分け

| 用途 | フォルダ |
|---|---|
| 論文原稿(和文)・国内発表・研究室内共有 | `ja/` |
| 国際学会のスライド・ポスター・英語論文 | `en/` |

図のファイル名は日英で共通（`fig_af41_loss_ablation` 等）。中身のラベル・タイトル・
凡例が日本語か英語かの違い。**両者は同一の実データ**（`../frr/` 配下）から生成される。

## データ・条件（両版共通）

- 全環境でCR帯域=9G、送信レート=8G/クラスに統一（送信・リンク条件を揃えて交絡を排除）
- 比較変数はSP有無(Strict Priority)と環境(veth/C2)の2つのみ
- 元データの詳細と数値表は `ja/veth_c1_c2_comparison_table.md` を参照

## 再生成

```bash
# 日本語版
python3 results/20260721_veth_c1_c2_summary/ja/plot_sp_ablation.py
# 英語版
python3 results/20260721_veth_c1_c2_summary/en/plot_sp_ablation_en.py
```

どちらのスクリプトも実データ(`../frr/`)を都度パースするので、計測をやり直したら
再実行するだけで全図が最新化される。
