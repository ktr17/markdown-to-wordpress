# markdown-to-wordpress

Markdown ファイルを画像付きで WordPress に投稿する Python スクリプト

## 特徴

- Gutenberg ブロック形式変換
- 画像の自動アップロード・リネーム
- ハッシュベース重複管理

## セットアップ

1. `git clone https://github.com/ktr17/markdown-to-wordpress.git`
2. `pip install -r requirements.txt`
3. `.env` ファイル設定
   `.env.example`をリネームして、`.env`を作成してください
4. `python deploy.py your_post.md`

## 対象ユーザー

- Markdown で執筆している人
- WordPress を使用している人
