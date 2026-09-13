# 作業者
- 実装・測定を行う別の Claude セッション。成果物は `Claude outputs/*.zip` か、PC の `engine/` への直接の書き戻しで届く。
  PC の `engine/` に無いときは `Claude outputs/` の zip を見る。
- 作業機は毎回同じとは限らない。**便 M は Anthropic のクラウドの作業機（2 コア）で回した**——
  Rust は `rust/src` から Linux 用に作り直し（PC には戻していない）、速さは PC の**およそ半分**
  （Rust 固定 n 0.40 局/秒・Python の champion ミラー 0.18 局/秒）。**結果はシード決定的なので数字は機械によらない。**
- 直近: 便 D 後半を 2026-09-09 に完了（`meicho_bin_d2.zip`・D-075）。**便 M を 2026-09-10 に完了（D-076）**——
  成果物 27 ファイルは PC の `engine/` に書き戻し済み。次は便 C。
