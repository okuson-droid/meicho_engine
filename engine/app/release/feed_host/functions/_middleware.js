// MeichoSim の更新元の門番（Cloudflare Pages Functions・APP-011）。
//
// 置き場のすべての要求の前に動く。起動役が送るヘッダ X-MeichoSim-Key が、秘密の設定 FEED_KEY と
// 同じときだけ中身を返す。違えば、何があるかを教えないために 404 を返す。FEED_KEY が未設定のときも
// 404 にする（設定を忘れたまま公開しても、開いた状態にならない）。
//
// これは暗号的な守りではない。起動役を持つ人は合言葉を読める。守るのは「URL だけが漏れたときに、
// 起動役を持たない人が中身を取れない」ことまでで、更新の正しさは起動役の側の署名の検証が守る。

function same(a, b) {
  // 長さと中身を、途中で打ち切らずに比べる（応答の時間から 1 文字ずつ当てられないように）
  let diff = a.length ^ b.length;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ (b.charCodeAt(i % Math.max(b.length, 1)) || 0);
  return diff === 0;
}

function notFound() {
  return new Response("Not found\n", {
    status: 404,
    headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}

export async function onRequest(context) {
  const want = context.env.FEED_KEY || "";
  const got = context.request.headers.get("X-MeichoSim-Key") || "";
  if (want.length < 16 || !same(want, got)) return notFound();
  if (context.request.method !== "GET" && context.request.method !== "HEAD") return notFound();
  const res = await context.next();
  const out = new Response(res.body, res);
  out.headers.set("X-Robots-Tag", "noindex, nofollow");
  // 合言葉つきの応答を、途中の共有キャッシュに残させない
  out.headers.set("Cache-Control", "private, no-cache");
  return out;
}
