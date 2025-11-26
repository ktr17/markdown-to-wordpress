# markdown-to-wordpress

Markdown ファイルを画像付きで WordPress に投稿する Python スクリプト

## 特徴

- Gutenberg ブロック形式変換
- 画像の自動アップロード・リネーム
- 画像のハッシュベース重複管理

## Markdown 記法

- コードブロック対応
- 内部リンク対応
- 脚注対応

## セットアップ

### Wordpress サーバ側

1. ssh で Wordpress サーバへ接続
2. wp-cli をインストール

   - `curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar`

   - インストールは任意のフォルダで実施してください。

### ローカル PC 側

1. `git clone https://github.com/ktr17/markdown-to-wordpress.git`
2. `pip install -r requirements.txt`
3. `.env` ファイル設定
   `.env.example`をリネームして、`.env`を作成してください
4. `python deploy.py your_post.md`

## 対象ユーザ

- Markdown で執筆している人
- WordPress を使用している人
