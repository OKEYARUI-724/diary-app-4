# 写真日記 + YouTube音楽検索 デモ

Spotify Premiumを使わずに、YouTube Data API v3で「写真 + 今日の1曲」を実装したデモです。

## できること

- 写真を選択して投稿
- YouTubeで曲名・アーティスト名・MVなどを検索
- 検索結果のサムネイル、タイトル、チャンネル名を表示
- 検索結果をYouTubeで確認してから1つ選択
- 写真プレビュー上に音楽カードを表示
- 投稿時はYouTube動画IDをサーバー側で再確認してからDBに保存
- 投稿一覧でも音楽カードを表示
- 音楽カードを押すと、画面内に正式なYouTube埋め込みプレイヤーを表示
- 「YouTubeで開く」から元動画も開ける

> YouTube動画を隠してBGMだけ流す実装にはしていません。再生時はYouTubeの埋め込みプレイヤーを見える状態で表示します。

---

## 1. YouTube APIキーを作る

Google Cloud Consoleを開きます。

1. Googleアカウントでログイン
2. 新しいプロジェクトを作成（既存プロジェクトでもOK）
3. 「APIとサービス」→「ライブラリ」
4. `YouTube Data API v3` を検索
5. 「有効にする」
6. 「APIとサービス」→「認証情報」
7. 「認証情報を作成」→「APIキー」
8. 表示されたAPIキーをコピー

### APIキーの制限（推奨）

ローカル開発中は、まず動作確認を優先して利用できます。動作確認後は、Google CloudのAPIキー設定で「APIの制限」を `YouTube Data API v3` のみにしてください。

APIキーはブラウザJavaScriptへ直接埋め込まず、このプロジェクトではFastAPI側だけで使います。

---

## 2. `.env` を作る

VS Codeでこのプロジェクトを開き、ターミナルで実行します。

```powershell
Copy-Item .env.example .env
```

`.env`を開いて、取得したAPIキーを入れます。

```env
YOUTUBE_API_KEY=ここに取得したAPIキー
```

例：

```env
YOUTUBE_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

実際のAPIキーは他人に送ったり、GitHubへアップロードしたりしないでください。
`.env`は`.gitignore`に入っています。

---

## 3. Dockerで起動

```powershell
docker compose down
```

続けて、

```powershell
docker compose up --build
```

起動したらブラウザで開きます。

```text
http://localhost:8000
```

---

## 4. 使い方

1. 写真を選ぶ
2. 「音楽を追加」の検索欄に曲名またはアーティスト名を入力
3. 「検索」を押す
4. 必要なら「YouTubeで確認」を押して動画を確認
5. 「この曲を選ぶ」
6. 写真上に音楽カードが出る
7. 「投稿する」
8. 投稿に表示された音楽カードを押す
9. YouTubeプレイヤーが開いて再生できる

---

## API

### YouTube検索

```http
GET /api/music/search?q=NewJeans&limit=10
```

返却例：

```json
{
  "items": [
    {
      "youtube_video_id": "XXXXXXXXXXX",
      "title": "Video title",
      "artist": "Channel name",
      "cover_url": "https://...",
      "external_url": "https://www.youtube.com/watch?v=XXXXXXXXXXX",
      "embed_url": "https://www.youtube.com/embed/XXXXXXXXXXX"
    }
  ]
}
```

### 投稿一覧

```http
GET /api/posts
```

### 投稿作成

`multipart/form-data`で以下を送ります。

- `image`: 写真
- `caption`: 本文（任意）
- `youtube_video_id`: 選択したYouTube動画ID（任意）

タイトルやチャンネル名をブラウザからそのままDBへ保存するのではなく、投稿時にFastAPIがYouTube APIから再取得します。

---

## Spotify版から変更した点

不要になったもの：

```env
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
```

代わりに必要なのはこれだけです。

```env
YOUTUBE_API_KEY=...
```

Spotify Premiumは不要です。

---

## 既存の写真日記アプリに組み込む場合

今回共有されている元プロジェクトはDocker関連ファイルが中心だったため、このフォルダは「そのまま起動できるYouTube版デモ」として作っています。

既存の投稿画面・ユーザー認証・いいね・コメントなどがすでにある場合は、元アプリの `app`、`templates` / `static`、またはフロントエンドのソース一式に、このYouTube検索APIと `youtube_video_id` を統合してください。
