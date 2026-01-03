#!/usr/bin/env python3
"""
Markdown to WordPress Publisher
Markdownファイルを画像付きでWordPressに投稿するメインスクリプト
内部リンク変換機能付き + 脚注対応
"""

import subprocess, sys, yaml, os, re, shutil, hashlib, json, uuid
from urllib.parse import unquote
from typing import List, Dict, Tuple
from config import get_config

def ssh_cmd(config, cmd):
    """SSH コマンドを構築"""
    return ["ssh", "-i", config.ssh_key, "-p", str(config.ssh_port),
            f"{config.server_user}@{config.server_host}", f"bash -l -c '{cmd}'"]

def scp_cmd(config, local_path, remote_name):
    """SCP コマンドを構築"""
    remote_tmp_dir = f"{config.wp_path}/{config.tmp_dir}"
    subprocess.run(ssh_cmd(config, f"mkdir -p {remote_tmp_dir}"), check=True)
    remote_tmp_path = f"{remote_tmp_dir}/{remote_name}"
    return ["scp", "-i", config.ssh_key, "-P", str(config.ssh_port), local_path,
            f"{config.server_user}@{config.server_host}:{remote_tmp_path}"]

def parse_frontmatter(md_file):
    """Markdownファイルのフロントマターを解析"""
    with open(md_file, encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return yaml.safe_load(m.group(1)) if m else {}

def write_frontmatter(md_file, fm):
    """フロントマターをMarkdownファイルに書き込み"""
    with open(md_file, encoding="utf-8") as f:
        text = f.read()
    new_fm = yaml.dump(fm, allow_unicode=True, sort_keys=False)
    if text.startswith("---"):
        new_text = re.sub(r"---\n.*?\n---", f"---\n{new_fm}---", text, flags=re.S)
    else:
        new_text = f"---\n{new_fm}---\n\n{text}"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(new_text)

def get_file_hash(file_path):
    """ファイルのハッシュ値を取得"""
    with open(file_path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()[:8]  # 短縮版

def upload_new_image(config, image_path, slug, file_hash):
    """ハッシュベースの名前でアップロード"""
    ext = os.path.splitext(image_path)[1]
    wp_filename = f"{slug}-{file_hash}{ext}"

    print(f"   アップロード開始: {wp_filename}")
    print(f"   元ファイル: {image_path}")

    # サーバにアップロード
    try:
        subprocess.run(scp_cmd(config, image_path, wp_filename), check=True)
        print(f"   ✅ SCP完了")
    except subprocess.CalledProcessError as e:
        print(f"   ❌ SCP失敗: {e}")
        raise

    # WordPressにインポート
    import_cmd = f"cd {config.wp_path}/{config.tmp_dir} && {config.wp_cli} media import {wp_filename} --porcelain && rm {wp_filename}"
    print(f"   WP-CLI実行: {import_cmd}")

    try:
        media_id = subprocess.check_output(
            ssh_cmd(config, import_cmd),
            text=True
        ).strip()
        print(f"   ✅ WordPress インポート完了: ID {media_id}")
    except subprocess.CalledProcessError as e:
        print(f"   ❌ WordPress インポート失敗: {e}")
        # エラー詳細を取得
        try:
            error_output = subprocess.check_output(
                ssh_cmd(config, f"cd {config.wp_path}/{config.tmp_dir} && {config.wp_cli} media import {wp_filename} && rm {wp_filename}"),
                text=True,
                stderr=subprocess.STDOUT
            )
            print(f"   エラー詳細: {error_output}")
        except:
            pass
        raise

    # URLを取得
    try:
        wp_url = subprocess.check_output(
            ssh_cmd(config, f"cd {config.wp_path} && {config.wp_cli} post get {media_id} --field=guid"),
            text=True
        ).strip()
        print(f"   ✅ URL取得完了: {wp_url}")
    except subprocess.CalledProcessError as e:
        print(f"   ❌ URL取得失敗: {e}")
        raise

    return media_id, wp_url

def find_obsidian_vault_root(md_file):
    """ObsidianのVault root ディレクトリを探す(.obsidianフォルダを探す)"""
    current_dir = os.path.dirname(os.path.abspath(md_file))

    while current_dir != os.path.dirname(current_dir):  # ルートディレクトリまで
        obsidian_dir = os.path.join(current_dir, '.obsidian')
        if os.path.exists(obsidian_dir):
            return current_dir
        current_dir = os.path.dirname(current_dir)

    return None

def resolve_image_path(md_file, img_path):
    """
    Obsidianの画像パスを解決する
    - 保管庫内絶対パス (images/sample.jpg)
    - ファイル相対パス (./images/sample.jpg)
    - URLエンコーディングされたパス (Pasted%20image%2020240210150905.png)
    両方に対応
    """
    if img_path.startswith('http'):
        return None  # URLはスキップ

    # URLデコードを実行
    decoded_img_path = unquote(img_path)
    print(f"   画像パス解決: '{img_path}' -> '{decoded_img_path}'")

    md_dir = os.path.dirname(os.path.abspath(md_file))

    # 元のパスとデコード後のパス両方で試行
    paths_to_try = [img_path, decoded_img_path]

    for current_path in paths_to_try:
        print(f"   試行パス: {current_path}")

        # 相対パス (./や../で始まる) の場合
        if current_path.startswith('./') or current_path.startswith('../'):
            abs_path = os.path.normpath(os.path.join(md_dir, current_path))
            print(f"     相対パス試行: {abs_path}")
            if os.path.exists(abs_path):
                print(f"     ✅ 発見(相対): {abs_path}")
                return abs_path

        # 保管庫内絶対パス (images/sample.jpgなど) の場合
        vault_root = find_obsidian_vault_root(md_file)
        if vault_root:
            vault_abs_path = os.path.normpath(os.path.join(vault_root, current_path))
            print(f"     Vault絶対パス試行: {vault_abs_path}")
            if os.path.exists(vault_abs_path):
                print(f"     ✅ 発見(Vault): {vault_abs_path}")
                return vault_abs_path

        # 通常の相対パスとして試行（後方互換性）
        normal_relative = os.path.normpath(os.path.join(md_dir, current_path))
        print(f"     通常相対パス試行: {normal_relative}")
        if os.path.exists(normal_relative):
            print(f"     ✅ 発見(通常): {normal_relative}")
            return normal_relative

    print(f"   ❌ 全ての試行で画像が見つかりませんでした")
    return None

def resolve_markdown_link_path(md_file, link_path):
    """
    Obsidianのマークダウンリンクパスを解決する
    画像と同じロジックを使用（.md拡張子付き）
    """
    if link_path.startswith('http'):
        return None  # URLはスキップ

    # URLデコードを実行
    decoded_link_path = unquote(link_path)

    # .md拡張子がなければ追加
    if not decoded_link_path.endswith('.md'):
        decoded_link_path += '.md'

    print(f"   リンクパス解決: '{link_path}' -> '{decoded_link_path}'")

    md_dir = os.path.dirname(os.path.abspath(md_file))

    # 元のパスとデコード後のパス両方で試行
    paths_to_try = [link_path, decoded_link_path]

    for current_path in paths_to_try:
        # .md拡張子がなければ追加
        if not current_path.endswith('.md'):
            current_path += '.md'

        print(f"   試行パス: {current_path}")

        # 相対パス (./や../で始まる) の場合
        if current_path.startswith('./') or current_path.startswith('../'):
            abs_path = os.path.normpath(os.path.join(md_dir, current_path))
            print(f"     相対パス試行: {abs_path}")
            if os.path.exists(abs_path):
                print(f"     ✅ 発見(相対): {abs_path}")
                return abs_path

        # 保管庫内絶対パス
        vault_root = find_obsidian_vault_root(md_file)
        if vault_root:
            vault_abs_path = os.path.normpath(os.path.join(vault_root, current_path))
            print(f"     Vault絶対パス試行: {vault_abs_path}")
            if os.path.exists(vault_abs_path):
                print(f"     ✅ 発見(Vault): {vault_abs_path}")
                return vault_abs_path

        # 通常の相対パスとして試行（後方互換性）
        normal_relative = os.path.normpath(os.path.join(md_dir, current_path))
        print(f"     通常相対パス試行: {normal_relative}")
        if os.path.exists(normal_relative):
            print(f"     ✅ 発見(通常): {normal_relative}")
            return normal_relative

    print(f"   ❌ 全ての試行でリンク先ファイルが見つかりませんでした")
    return None

def get_wordpress_link_data_from_md(config, md_file_path):
    """
    Markdownファイルからwp_id、slug、titleを読み取り、リンクデータを生成
    """
    try:
        fm = parse_frontmatter(md_file_path)
        wp_id = fm.get('wp_id')
        slug = fm.get('slug')
        title = fm.get('title', os.path.splitext(os.path.basename(md_file_path))[0])

        if not wp_id:
            print(f"   ⚠️ リンク先ファイルにwp_idが設定されていません: {md_file_path}")
            return None

        # WordPress URLを生成（設定のsite_urlを使用）
        site_url = config.site_url.rstrip('/')

        wp_url = f"{site_url}/?p={wp_id}"

        link_data = {
            'title': title,
            'id': wp_id,
            'url': wp_url
        }

        print(f"   ✅ リンクデータ生成: ID={wp_id}, タイトル={title}")
        return link_data

    except Exception as e:
        print(f"   ❌ リンク先ファイルの読み込みエラー: {e}")
        return None

def process_internal_links(config, md_file, text):
    """
    Markdown内のローカルリンクをWordPress内部リンクブロック（Gutenberg）に変換
    [リンクテキスト](ファイル名.md) → <!-- wp:loos/post-link ... /-->
    """
    print("内部リンク変換処理開始...")

    # Markdownリンクパターン [text](link)
    link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'

    # 変換されたリンクを保存（後でまとめて置換）
    links_to_replace = []

    def analyze_link(match):
        link_text = match.group(1)
        link_path = match.group(2)

        # 外部URL、アンカーリンク、画像はスキップ
        if link_path.startswith('http') or link_path.startswith('#') or link_path.startswith('!'):
            return None

        # .mdファイルへのリンクのみ処理
        if not link_path.endswith('.md') and not os.path.splitext(link_path)[1] == '':
            return None

        print(f"内部リンク検出: [{link_text}]({link_path})")

        # リンク先のMarkdownファイルパスを解決
        abs_link_path = resolve_markdown_link_path(md_file, link_path)

        if not abs_link_path:
            print(f"   ⚠️ リンク先ファイルが見つからないためスキップ: {link_path}")
            return None

        # リンク先のWordPressリンクデータを取得
        link_data = get_wordpress_link_data_from_md(config, abs_link_path)

        if not link_data:
            print(f"   ⚠️ リンクデータが取得できないためスキップ: {link_path}")
            return None

        # Gutenberg内部リンクブロックを生成
        link_data_json = json.dumps({
            "title": link_data['title'],
            "id": link_data['id'],
            "url": link_data['url'],
            "kind": "post-type",
            "type": "post"
        }, ensure_ascii=False)

        gutenberg_link = f'<!-- wp:loos/post-link {{"linkData":{link_data_json},"icon":"link"}} /-->'

        print(f"   ✅ 変換完了: Gutenbergブロック生成")

        return {
            'original': match.group(0),
            'replacement': gutenberg_link
        }

    # すべてのリンクを解析
    for match in re.finditer(link_pattern, text):
        result = analyze_link(match)
        if result:
            links_to_replace.append(result)

    # 置換を実行
    converted_text = text
    for link in links_to_replace:
        converted_text = converted_text.replace(link['original'], link['replacement'])

    print(f"✅ 内部リンク変換処理完了: {len(links_to_replace)}個のリンクを変換")
    return converted_text

def rename_local_image(original_path, new_filename):
    """ローカル画像ファイルをリネーム"""
    original_dir = os.path.dirname(original_path)
    new_path = os.path.join(original_dir, new_filename)

    # 既に同名ファイルが存在する場合は何もしない
    if original_path == new_path:
        return new_path

    # リネーム実行
    if os.path.exists(original_path):
        # 移行先に既にファイルが存在する場合の対処
        if os.path.exists(new_path):
            print(f"   警告: リネーム先ファイルが既に存在: {new_path}")
            # ハッシュを比較して同じファイルかチェック
            if get_file_hash(original_path) == get_file_hash(new_path):
                print(f"   同一ファイルのため元ファイルを削除: {original_path}")
                os.remove(original_path)
                return new_path
            else:
                print(f"   異なるファイルのためリネームをスキップ: {original_path}")
                return original_path
        else:
            shutil.move(original_path, new_path)
            print(f"   ✅ ローカル画像リネーム: {os.path.basename(original_path)} -> {new_filename}")
            return new_path

    return original_path

def sanitize_filename(text):
    """ファイル名として安全な文字列に変換（日本語対応）"""
    # ファイル名に使えない文字を削除・置換
    unsafe_chars = r'[<>:"/\\|?*]'
    text = re.sub(unsafe_chars, '-', text)
    # 連続するハイフンを単一に
    text = re.sub(r'-+', '-', text)
    # 前後の空白・ハイフンを削除
    text = text.strip(' -')
    # 空の場合はデフォルト値
    if not text:
        text = 'untitled'
    return text

# ===== Gutenberg ブロック変換関数 =====

def escape_html(text):
    """HTMLエスケープ（コードブロック用に最小限に）"""
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))

def process_inline_formatting(text, footnote_counter=None):
    """インライン記法を処理（太字、斜体、リンク、インラインコード、脚注）"""
    # ショートコードを含む行は処理をスキップ
    if re.search(r'\[[\w\-_]+[^\]]*\]', text):
        return text

    # インラインコード（最初に処理して他の記法との競合を避ける）
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # 太字
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.*?)__', r'<strong>\1</strong>', text)

    # 斜体
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = re.sub(r'_(.*?)_', r'<em>\1</em>', text)

    # 脚注参照（footnote_counterが提供されている場合のみ）
    if footnote_counter is not None:
        def replace_footnote_ref(match):
            ref_id = match.group(1)
            if ref_id in footnote_counter:
                uuid_id, num = footnote_counter[ref_id]
                return f'<sup data-fn="{uuid_id}" class="fn"><a href="#{uuid_id}" id="{uuid_id}-link">{num}</a></sup>'
            return match.group(0)

        text = re.sub(r'\[\^([^\]]+)\]', replace_footnote_ref, text)

    # リンク（脚注参照の後に処理）
    text = re.sub(r'\[([^\]^]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', text)

    return text

def convert_urls_to_links(text: str) -> str:
    """
    テキスト内のURLを自動的にHTMLリンクに変換
    """
    # URLパターン (http:// または https:// で始まる)
    url_pattern = r'(https?://[^\s]+)'

    def replace_url(match):
        url = match.group(1)
        # URLの末尾の句読点を除外
        punctuation = ''
        while url and url[-1] in '.,;:!?)':
            punctuation = url[-1] + punctuation
            url = url[:-1]
        return f'<a href="{url}">{url}</a>{punctuation}'

    return re.sub(url_pattern, replace_url, text)

def extract_footnotes(markdown_content: str) -> Tuple[str, Dict[str, str]]:
    """
    Markdownから脚注定義を抽出し、本文から削除

    Returns:
        (本文コンテンツ, {脚注ID: 脚注内容})
    """
    footnotes = {}
    lines = markdown_content.split('\n')
    content_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]
        # 脚注定義の検出: [^id]: 内容
        match = re.match(r'^\[\^([^\]]+)\]:\s*(.+)$', line)
        if match:
            footnote_id = match.group(1)
            footnote_text = match.group(2)

            # 複数行の脚注に対応（インデントされた続きの行）
            i += 1
            while i < len(lines) and (lines[i].startswith('    ') or lines[i].startswith('\t')):
                footnote_text += ' ' + lines[i].strip()
                i += 1

            footnotes[footnote_id] = footnote_text
            continue

        content_lines.append(line)
        i += 1

    return '\n'.join(content_lines), footnotes

def create_footnotes_block(footnotes: Dict[str, str], footnote_order: Dict[str, Tuple[str, int]]) -> str:
    """
    脚注をWordPress Gutenberg標準の脚注ブロックとして生成

    Args:
        footnotes: {脚注ID: 脚注内容}
        footnote_order: {脚注ID: (UUID, 表示番号)}
    """
    if not footnotes or not footnote_order:
        return ""

    # Gutenberg標準の脚注ブロック（wp:footnotesで自動生成される）
    return '<!-- wp:footnotes /-->'

def create_heading_block(content: str, level: int, footnote_counter=None) -> str:
    """見出しブロックを作成"""
    content = process_inline_formatting(content, footnote_counter)
    # H2はデフォルトなので属性を省略可能
    if level == 2:
        return f'<!-- wp:heading -->\n<h{level} class="wp-block-heading">{content}</h{level}>\n<!-- /wp:heading -->'
    else:
        attrs = json.dumps({"level": level})
        return f'<!-- wp:heading {attrs} -->\n<h{level} class="wp-block-heading">{content}</h{level}>\n<!-- /wp:heading -->'

def create_paragraph_block(content: str, footnote_counter=None) -> str:
    """段落ブロックを作成"""
    if not content.strip():
        return ""
    content = process_inline_formatting(content, footnote_counter)
    return f'<!-- wp:paragraph -->\n<p>{content}</p>\n<!-- /wp:paragraph -->'

def create_image_block(url: str, alt: str = '') -> str:
    """画像ブロックを作成"""
    return f'<!-- wp:image -->\n<figure class="wp-block-image"><img src="{url}" alt="{alt}"/></figure>\n<!-- /wp:image -->'

def create_list_block(items: List[str], ordered: bool = False, footnote_counter=None) -> str:
    """リストブロックを作成"""
    tag = "ol" if ordered else "ul"
    attrs = json.dumps({"ordered": ordered}) if ordered else "{}"

    list_html = f'<{tag}>'
    for item in items:
        processed_item = process_inline_formatting(item, footnote_counter)
        list_html += f'<li>{processed_item}</li>'
    list_html += f'</{tag}>'

    return f'<!-- wp:list {attrs} -->\n{list_html}\n<!-- /wp:list -->'

def create_code_block(use_highlight_plugin: bool, code: str, language: str = '') -> str:
    """コードブロックを作成（Highlight Code Block対応）"""
    print(f"コードブロック作成: 言語={language}, USE_HIGHLIGHT_CODE_BLOCK={use_highlight_plugin}")

    if use_highlight_plugin:
        # Highlight Code Block プラグイン専用ブロック
        if language:
            # 言語名のマッピング（表示用）
            lang_display_names = {
                'python': 'Python',
                'php': 'PHP',
                'javascript': 'JavaScript',
                'js': 'JavaScript',
                'html': 'HTML',
                'css': 'CSS',
                'bash': 'Bash',
                'shell': 'Shell',
                'sql': 'SQL',
                'json': 'JSON',
                'xml': 'XML',
                'yaml': 'YAML',
                'yml': 'YAML'
            }

            lang_name = lang_display_names.get(language.lower(), language.capitalize())
            attrs = json.dumps({
                "langType": language,
                "langName": lang_name
            })
        else:
            # 言語指定なしの場合
            attrs = json.dumps({
                "langType": "text",
                "langName": "Text"
            })
            language = "text"

        # HTMLエスケープしたコード
        escaped_code = escape_html(code)

        # Highlight Code Block の正確な形式
        html_content = f'<div class="hcb_wrap"><pre class="prism undefined-numbers lang-{language}" data-lang="{lang_name if language != "text" else "Text"}"><code>{escaped_code}</code></pre></div>'

        result = f'<!-- wp:loos-hcb/code-block {attrs} -->\n{html_content}\n<!-- /wp:loos-hcb/code-block -->'
        print(f"Highlight Code Block形式で生成")
        return result

    elif language:
        # WordPress標準コードブロック（言語指定あり）
        attrs = json.dumps({"language": language})
        result = f'<!-- wp:code {attrs} -->\n<pre class="wp-block-code"><code lang="{language}" class="language-{language}">{code}</code></pre>\n<!-- /wp:code -->'
        print(f"WordPress標準（言語あり）で生成")
        return result
    else:
        # WordPress標準コードブロック（言語指定なし）
        result = f'<!-- wp:code -->\n<pre class="wp-block-code"><code>{code}</code></pre>\n<!-- /wp:code -->'
        print(f"WordPress標準（言語なし）で生成")
        return result

def parse_table(lines: List[str], start_index: int) -> Tuple[List[str], int]:
    """テーブル行を解析"""
    table_lines = []
    i = start_index

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('|') and line.endswith('|'):
            table_lines.append(line)
        elif line == '':
            # 空行は続行
            pass
        else:
            # テーブルでない行で終了
            break
        i += 1

    return table_lines, i - 1

def create_table_block(table_lines: List[str], footnote_counter=None) -> str:
    """テーブルブロックを作成"""
    if len(table_lines) < 2:
        return ""

    # ヘッダー行とセパレーター行を除いてボディ行を取得
    header_line = table_lines[0]
    body_lines = table_lines[2:] if len(table_lines) > 2 else []

    # ヘッダーセルを解析
    header_cells = [cell.strip() for cell in header_line.split('|') if cell.strip()]

    # ボディ行を解析
    body_rows = []
    for line in body_lines:
        cells = [cell.strip() for cell in line.split('|') if cell.strip()]
        if cells:  # 空でない行のみ
            body_rows.append(cells)

    # HTMLテーブルを構築（正しいクラス名を使用）
    table_html = '<table class="has-fixed-layout"><thead><tr>'

    # ヘッダー
    for cell in header_cells:
        processed_cell = process_inline_formatting(cell, footnote_counter)
        table_html += f'<th>{processed_cell}</th>'
    table_html += '</tr></thead><tbody>'

    # ボディ
    for row in body_rows:
        table_html += '<tr>'
        for i, cell in enumerate(row):
            if i < len(header_cells):  # ヘッダー数と合わせる
                processed_cell = process_inline_formatting(cell, footnote_counter)
                table_html += f'<td>{processed_cell}</td>'
        table_html += '</tr>'

    table_html += '</tbody></table>'

    return f'<!-- wp:table -->\n<figure class="wp-block-table">{table_html}</figure>\n<!-- /wp:table -->'

def create_quote_block(content: str, footnote_counter=None) -> str:
    """引用ブロックを作成（内部に段落ブロックを含める）"""
    content = process_inline_formatting(content, footnote_counter)
    # 引用ブロック内に段落ブロックを含める形式
    return f'<!-- wp:quote -->\n<blockquote class="wp-block-quote"><!-- wp:paragraph -->\n<p>{content}</p>\n<!-- /wp:paragraph --></blockquote>\n<!-- /wp:quote -->'

def parse_list_items(lines: List[str], start_index: int) -> Tuple[List[str], int, bool]:
    """リストアイテムを解析"""
    items = []
    i = start_index
    ordered = False

    # 最初の行でリストタイプを判定
    first_line = lines[i].strip()
    if re.match(r'^\d+\.', first_line):
        ordered = True
        pattern = r'^\d+\.\s*(.*)'
    else:
        pattern = r'^[-*+]\s*(.*)'

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            # 空行をチェック（リスト終了の可能性）
            if i + 1 < len(lines) and not re.match(r'^[-*+\d]', lines[i + 1].strip()):
                break
            i += 1
            continue

        match = re.match(pattern, line)
        if match:
            items.append(match.group(1))
        else:
            # リストアイテムでない場合は終了
            break
        i += 1

    return items, i - 1, ordered

def parse_code_block(lines: List[str], start_index: int) -> Tuple[str, str, int]:
    """コードブロックを解析"""
    start_line = lines[start_index].strip()
    language_match = re.match(r'^```(\w*)', start_line)
    language = language_match.group(1) if language_match and language_match.group(1) else ''

    code_lines = []
    i = start_index + 1

    while i < len(lines):
        if lines[i].strip() == '```':
            break
        code_lines.append(lines[i])
        i += 1

    code = '\n'.join(code_lines)
    return code, language, i

def markdown_to_gutenberg(markdown_content: str, use_highlight_plugin: bool) -> Tuple[str, List[Dict]]:
    """MarkdownをGutenbergブロック形式に変換（脚注対応）

    Returns:
        (Gutenbergコンテンツ, 脚注メタデータのリスト)
    """
    print("Markdown → Gutenberg変換開始...")

    # 脚注を抽出
    content_without_footnotes, footnotes = extract_footnotes(markdown_content)
    print(f"脚注検出: {len(footnotes)}個")

    # 脚注の出現順序を記録（UUID, 番号のタプル）
    footnote_order = {}
    footnote_counter_num = 1

    # 本文中の脚注参照を検出して番号とUUIDを割り当て
    for match in re.finditer(r'\[\^([^\]]+)\]', content_without_footnotes):
        footnote_id = match.group(1)
        if footnote_id not in footnote_order and footnote_id in footnotes:
            # UUIDv4を生成
            footnote_uuid = str(uuid.uuid4())
            footnote_order[footnote_id] = (footnote_uuid, footnote_counter_num)
            footnote_counter_num += 1

    blocks = []
    lines = content_without_footnotes.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 空行をスキップ
        if not stripped:
            i += 1
            continue

        # 見出し
        if stripped.startswith('#'):
            level = len(stripped) - len(stripped.lstrip('#'))
            if level <= 6:  # H1-H6のみ
                content = stripped.lstrip('#').strip()
                blocks.append(create_heading_block(content, level, footnote_order))
                i += 1
                continue

        # コードブロック
        if stripped.startswith('```'):
            code, language, end_index = parse_code_block(lines, i)
            blocks.append(create_code_block(use_highlight_plugin, code, language))
            i = end_index + 1
            continue

        # テーブル
        if stripped.startswith('|') and stripped.endswith('|'):
            table_lines, end_index = parse_table(lines, i)
            if len(table_lines) >= 2:  # ヘッダーとセパレーターが最低限必要
                blocks.append(create_table_block(table_lines, footnote_order))
                i = end_index + 1
                continue

        # 引用
        if stripped.startswith('>'):
            quote_content = stripped.lstrip('>').strip()
            blocks.append(create_quote_block(quote_content, footnote_order))
            i += 1
            continue

        # リスト
        if re.match(r'^[-*+]\s', stripped) or re.match(r'^\d+\.\s', stripped):
            items, end_index, ordered = parse_list_items(lines, i)
            if items:
                blocks.append(create_list_block(items, ordered, footnote_order))
            i = end_index + 1
            continue

        # 画像
        img_match = re.match(r'!\[([^\]]*)\]\(([^)]*)\)', stripped)
        if img_match:
            alt_text = img_match.group(1)
            img_url = img_match.group(2)
            blocks.append(create_image_block(img_url, alt_text))
            i += 1
            continue

        # 段落（複数行をまとめる）
        paragraph_lines = []
        while i < len(lines):
            current_line = lines[i].strip()

            # 段落終了条件をチェック
            if not current_line:
                break
            if current_line.startswith('#'):
                break
            if current_line.startswith('```'):
                break
            if current_line.startswith('>'):
                break
            if re.match(r'^[-*+]\s', current_line) or re.match(r'^\d+\.\s', current_line):
                break
            if re.match(r'!\[.*\]\(.*\)', current_line):
                break

            paragraph_lines.append(current_line)
            i += 1

        if paragraph_lines:
            paragraph_content = ' '.join(paragraph_lines)
            block = create_paragraph_block(paragraph_content, footnote_order)
            if block:  # 空でない場合のみ追加
                blocks.append(block)

    # 脚注ブロックを最後に追加（Gutenberg標準形式）
    footnotes_meta = []
    if footnotes and footnote_order:
        footnotes_block = create_footnotes_block(footnotes, footnote_order)
        blocks.append(footnotes_block)

        # post_meta用の脚注データを生成（URLを自動リンク化）
        for footnote_id, (footnote_uuid, num) in sorted(footnote_order.items(), key=lambda x: x[1][1]):
            if footnote_id in footnotes:
                # 脚注内容のURLを自動的にリンクに変換
                footnote_content = convert_urls_to_links(footnotes[footnote_id])

                footnote_data = {
                    'id': footnote_uuid,
                    'content': footnote_content
                }
                footnotes_meta.append(footnote_data)
                print(f"   脚注 [{num}]: UUID={footnote_uuid}, 内容={footnote_content[:80]}...")

        print(f"✅ 脚注ブロック追加: {len(footnote_order)}個の脚注")
        print(f"✅ 脚注メタデータ生成: {len(footnotes_meta)}個")

    result = '\n\n'.join(blocks)
    print(f"✅ Gutenberg変換完了: {len(blocks)}個のブロックを生成")
    return result, footnotes_meta

def process_images_with_local_rename(config, md_file, slug):
    """
    ローカル画像をリネームし、Markdownファイル内のリンクも更新
    その後WordPress用コンテンツを生成
    """
    with open(md_file, encoding="utf-8") as f:
        text = f.read()

    fm = parse_frontmatter(md_file)
    image_map = fm.get('wp_images') or {}

    images = re.findall(r'!\[([^\]]*)\]\(([^)]*)\)', text)  # alt text も取得
    wp_text = text
    local_text = text
    image_counter = 1

    # ファイル名として安全なslugを生成
    safe_slug = sanitize_filename(slug)

    for alt_text, img_path in images:
        # URLデコード
        decoded_img_path = unquote(img_path)
        print(f"画像処理開始: {decoded_img_path}")

        # Obsidian形式の画像パスを解決
        abs_path = resolve_image_path(md_file, decoded_img_path)

        if abs_path:
            # 新しいローカルファイル名を生成
            ext = os.path.splitext(abs_path)[1]
            new_local_filename = f"{safe_slug}-{image_counter:02d}{ext}"

            # ローカル画像をリネーム
            new_abs_path = rename_local_image(abs_path, new_local_filename)

            # 新しいローカルパスを計算（Markdownファイルからの相対パス）
            md_dir = os.path.dirname(os.path.abspath(md_file))
            vault_root = find_obsidian_vault_root(md_file)

            if vault_root and new_abs_path.startswith(vault_root):
                new_local_path = os.path.relpath(new_abs_path, vault_root)
            else:
                new_local_path = os.path.relpath(new_abs_path, md_dir)

            # Markdown内リンク更新
            old_link = f"![{alt_text}]({img_path})"
            new_link = f"![{alt_text}]({new_local_path})"
            local_text = local_text.replace(old_link, new_link)
            print(f"   ローカルリンク更新: {img_path} -> {new_local_path}")

            # WordPress用処理
            file_hash = get_file_hash(new_abs_path)

            if file_hash in image_map:
                # 既存画像を使用
                wp_info = image_map[file_hash]
                wp_url = wp_info['url']
                print(f"   既存画像使用: {wp_url}")
                # original_path を最新に更新
                image_map[file_hash]['original_path'] = new_local_path
            else:
                # 新規アップロード
                media_id, wp_url = upload_new_image(config, new_abs_path, safe_slug, file_hash)
                image_map[file_hash] = {
                    'id': media_id,
                    'url': wp_url,
                    'original_path': new_local_path
                }
                print(f"   新規アップロード: ID {media_id}")

            # WordPress投稿用テキスト更新
            wp_link = f"![{alt_text}]({wp_url})"
            wp_text = wp_text.replace(old_link, wp_link)

            image_counter += 1
        else:
            print(f"   ❌ 画像ファイルが見つかりません: {decoded_img_path}")

    # フロントマターに必ず image_map を反映
    fm['wp_images'] = image_map

    # Markdown更新
    if local_text != text:
        content_only = re.sub(r'^---.*?---\n', '', local_text, flags=re.DOTALL)
        new_fm = yaml.dump(fm, allow_unicode=True, sort_keys=False)
        updated_md = f"---\n{new_fm}---\n{content_only}"

        with open(md_file, "w", encoding="utf-8") as f:
            f.write(updated_md)
        print(f"✅ ローカルMarkdownファイル更新完了（画像リンク更新）")
    else:
        write_frontmatter(md_file, fm)

    return wp_text

def process_featured_image_with_hash_tracking(config, md_file, slug, featured_image_path):
    """アイキャッチ画像をハッシュベースで処理（Obsidian対応）+ ローカルリネーム"""
    if not featured_image_path or featured_image_path.startswith('http'):
        print(f"アイキャッチ画像: 指定なしまたはURL形式のためスキップ: {featured_image_path}")
        return "", ""

    print(f"アイキャッチ画像処理開始: {featured_image_path}")

    fm = parse_frontmatter(md_file)
    image_map = fm.get('wp_images') or {}

    decoded_path = unquote(featured_image_path)
    abs_thumb = resolve_image_path(md_file, decoded_path)
    if not abs_thumb:
        print(f"❌ アイキャッチ画像画像が見つかりません: {featured_image_path}")
        return "", ""

    safe_slug = sanitize_filename(slug)
    ext = os.path.splitext(abs_thumb)[1]
    new_filename = f"{safe_slug}-featured-image{ext}"
    new_abs_thumb = rename_local_image(abs_thumb, new_filename)

    md_dir = os.path.dirname(os.path.abspath(md_file))
    vault_root = find_obsidian_vault_root(md_file)
    if vault_root and new_abs_thumb.startswith(vault_root):
        new_featured_image_path = os.path.relpath(new_abs_thumb, vault_root)
    else:
        new_featured_image_path = os.path.relpath(new_abs_thumb, md_dir)

    print(f"   ローカルアイキャッチ画像リネーム: {featured_image_path} -> {new_featured_image_path}")

    # リネーム後のファイルでハッシュ計算
    file_hash = get_file_hash(new_abs_thumb)
    print(f"   ハッシュ値: {file_hash}")

    if file_hash in image_map and 'id' in image_map[file_hash]:
        # 既存アイキャッチ画像使用
        featured_image_id = image_map[file_hash]['id']
        print(f"✅ 既存アイキャッチ画像使用: ID {featured_image_id}")
        # original_path を最新に更新
        image_map[file_hash]['original_path'] = new_featured_image_path
    else:
        # 新規アップロード
        print(f"📤 新規アイキャッチ画像アップロード開始...")
        featured_image_id, wp_url = upload_new_image(config, new_abs_thumb, safe_slug, file_hash)
        image_map[file_hash] = {
            'id': featured_image_id,
            'url': wp_url,
            'original_path': new_featured_image_path
        }
        print(f"✅ 新規アイキャッチ画像アップロード完了: ID {featured_image_id}")
        print(f"   WordPress URL: {wp_url}")

    # フロントマターに必ず反映
    fm['wp_images'] = image_map

    write_frontmatter(md_file, fm)

    return featured_image_id, new_featured_image_path

def assign_images_to_post(config, wp_id, image_map):
    """既存の画像を投稿に割り当て"""
    for file_hash, img_info in image_map.items():
        if 'id' in img_info:
            media_id = img_info['id']
            # 現在のpost_parentを確認
            check_cmd = f"cd {config.wp_path} && {config.wp_cli} db query \"SELECT post_parent FROM wp_posts WHERE ID={media_id}\" --skip-column-names"
            current_parent = subprocess.check_output(ssh_cmd(config, check_cmd), text=True).strip()

            if current_parent != str(wp_id):
                # 投稿に割り当てられていない場合のみ更新
                update_cmd = f"cd {config.wp_path} && {config.wp_cli} db query \"UPDATE wp_posts SET post_parent={wp_id} WHERE ID={media_id}\""
                subprocess.run(ssh_cmd(config, update_cmd), check=True)
                print(f"   ✅ 画像ID {media_id} を投稿ID {wp_id} に割り当て")
            else:
                print(f"   既に割り当て済み: 画像ID {media_id} → 投稿ID {wp_id}")

def main(md_file):
    # 設定を取得
    config = get_config()

    base = os.path.splitext(os.path.basename(md_file))[0]
    fm = parse_frontmatter(md_file)

    if fm.get("private") == True:
        print(f"公開禁止ファイルのため、処理を終了します。")
        print(f"  private: true -> 公開不可")
        return

    if fm.get("private") == None:
        print(f"公開可否が設定されていないため、処理を終了します。")
        print(f"front-matterに 「private」 を設定してください。")
        print(f"  private: false -> 公開可能")
        print(f"  private: true  -> 公開不可")
        return

    wp_id = fm.get("wp_id")
    # フロントマターのtitleを優先、なければファイル名ベースを使用
    title = fm.get("title", base)
    slug = fm.get("slug", base)

    print(f"投稿タイトル: {title}")
    print(f"投稿スラッグ: {slug}")

    # tags と categories を安全に処理
    tags_raw = fm.get("tags", [])
    if isinstance(tags_raw, list):
        tags = ",".join(tags_raw)
    elif isinstance(tags_raw, str):
        tags = tags_raw
    else:
        tags = ""

    categories_raw = fm.get("categories", [])
    if isinstance(categories_raw, list):
        categories = ",".join(categories_raw)
    elif isinstance(categories_raw, str):
        categories = categories_raw
    else:
        categories = ""
    featured_image = fm.get("featured_image")

    # 本文画像処理（ローカルリネーム + ハッシュベース、WordPress URL変換版コンテンツを生成）
    wp_content = process_images_with_local_rename(config, md_file, slug)

    # 内部リンク変換処理を追加
    wp_content = process_internal_links(config, md_file, wp_content)

    # 全角のダブルクォート " " を ASCII の " に統一
    wp_content = wp_content.replace(""", "\"").replace(""", "\"")

    # アイキャッチ画像処理（ハッシュベース + ローカルリネーム）
    featured_image_id, new_featured_image_path = process_featured_image_with_hash_tracking(config, md_file, slug, featured_image)

    # wp-imagesが更新されたあとで、再度取得する
    fm = parse_frontmatter(md_file)

    # アイキャッチ画像のフロントマター更新処理
    featured_image_updated = False
    if new_featured_image_path and new_featured_image_path != featured_image:
        print(f"アイキャッチ画像パス更新: {featured_image} -> {new_featured_image_path}")
        fm["featured_image"] = new_featured_image_path
        featured_image_updated = True

    # ローカルMarkdownファイル更新（アイキャッチ画像パス変更も含む）
    if featured_image_updated:
        write_frontmatter(md_file, fm)
        print(f"✅ フロントマター更新完了（アイキャッチ画像パス変更）")

    # アイキャッチ設定用のオプション作成
    if featured_image_id:
        featured_image_opt = f"--featured_image={featured_image_id}"
        print(f"アイキャッチ設定: ID {featured_image_id}")
    else:
        featured_image_opt = ""
        print("アイキャッチ: 設定されません")

    # フロントマターを除いたMarkdownコンテンツを取得
    content_only = re.sub(r'^---.*?---\n', '', wp_content, flags=re.DOTALL)

    # MarkdownをGutenbergブロック形式に変換（脚注対応）
    gutenberg_content, footnotes_meta = markdown_to_gutenberg(content_only, config.use_highlight_code_block)

    # 一時的なGutenbergファイル作成
    gutenberg_file = f"{base}_gutenberg.txt"
    with open(gutenberg_file, "w", encoding="utf-8") as f:
        f.write(gutenberg_content)

    print(f"✅ Gutenbergブロック変換完了: {gutenberg_file}")

    # サーバにGutenbergコンテンツをアップロード
    subprocess.run(scp_cmd(config, gutenberg_file, gutenberg_file), check=True)

    # 投稿作成 or 更新
    if not wp_id:
        # 新規投稿（titleを確実に使用）
        cmd = (
            f"mkdir -p {config.wp_path}/{config.tmp_dir} && cd {config.wp_path}/{config.tmp_dir} && "
            f"{config.wp_cli} post create {gutenberg_file} --post_type=post "
            f"--post_status={config.post_status} --post_title='{title}' --post_name='{slug}' "
            f"--tags_input='{tags}' --post_category='{categories}' {featured_image_opt} --porcelain && "
            f"rm {gutenberg_file}"
        )
        new_id = subprocess.check_output(ssh_cmd(config, cmd), text=True).strip()
        fm["wp_id"] = int(new_id)

        # 画像の未割り当てを解消
        assign_images_to_post(config, new_id, fm.get('wp_images', {}))

        write_frontmatter(md_file, fm)
        print(f"✅ 新規投稿ID {new_id} を {md_file} に追記しました")
        print(f"✅ 投稿タイトル: '{title}' で作成されました")

        # アイキャッチ設定（もしあれば）
        if featured_image_id:
            set_thumb_cmd = (
                f"cd {config.wp_path} && {config.wp_cli} post meta set {new_id} _featured_image_id {featured_image_id}"
            )
            subprocess.run(ssh_cmd(config, set_thumb_cmd), check=True)
            print(f"✅ 新規投稿 {new_id} にアイキャッチ(ID {featured_image_id}) を設定しました")

        # 脚注メタデータを保存
        if footnotes_meta:
            footnotes_json = json.dumps(footnotes_meta, ensure_ascii=False)
            print(f"   保存する脚注JSON: {footnotes_json}")

            # ダブルクォートをエスケープ
            footnotes_json_escaped = footnotes_json.replace('\\', '\\\\').replace('"', '\\"')

            set_footnotes_cmd = (
                f"cd {config.wp_path} && {config.wp_cli} post meta set {new_id} footnotes \"{footnotes_json_escaped}\""
            )
            result = subprocess.run(ssh_cmd(config, set_footnotes_cmd), capture_output=True, text=True, check=True)
            print(f"✅ 新規投稿 {new_id} に脚注メタデータを保存しました（{len(footnotes_meta)}個）")

    else:
        # 既存投稿更新（タイトルも更新）
        # 本文、タイトル、タグ・カテゴリを更新
        cmd_update = (
            f"mkdir -p {config.wp_path}/{config.tmp_dir} && cd {config.wp_path}/{config.tmp_dir} && "
            f"{config.wp_cli} post update {wp_id} {gutenberg_file} "
            f"--post_title='{title}' --tags_input='{tags}' --post_category='{categories}' && "
            f"rm {gutenberg_file}"
        )

        # アイキャッチ（アイキャッチ画像）を別途設定
        cmd_thumb = ""
        if featured_image_id:
            cmd_thumb = f"{config.wp_cli} post meta set {wp_id} _featured_image_id {featured_image_id}"

        # まとめて実行
        cmd = cmd_update
        if cmd_thumb:
            cmd += f" && {cmd_thumb}"
        subprocess.run(ssh_cmd(config, cmd), check=True)

        # 画像の未割り当てを解消
        assign_images_to_post(config, wp_id, fm.get('wp_images', {}))

        print(f"✅ 投稿ID {wp_id} を更新しました")
        print(f"✅ 投稿タイトル: '{title}' に更新されました")

        # 脚注メタデータを更新
        if footnotes_meta:
            footnotes_json = json.dumps(footnotes_meta, ensure_ascii=False)
            print(f"   更新する脚注JSON: {footnotes_json}")

            # ダブルクォートをエスケープ
            footnotes_json_escaped = footnotes_json.replace('\\', '\\\\').replace('"', '\\"')

            update_footnotes_cmd = (
                f"cd {config.wp_path} && {config.wp_cli} post meta update {wp_id} footnotes \"{footnotes_json_escaped}\""
            )
            result = subprocess.run(ssh_cmd(config, update_footnotes_cmd), capture_output=True, text=True, check=True)
            print(f"✅ 投稿 {wp_id} の脚注メタデータを更新しました（{len(footnotes_meta)}個）")
        else:
            # 脚注がない場合はメタデータを削除
            delete_footnotes_cmd = (
                f"cd {config.wp_path} && {config.wp_cli} post meta delete {wp_id} footnotes"
            )
            # エラーを無視（メタデータが存在しない場合）
            subprocess.run(ssh_cmd(config, delete_footnotes_cmd), check=False)
            print(f"✅ 投稿 {wp_id} の脚注メタデータを削除しました（脚注なし）")

    # ローカルGutenbergファイルを削除
    os.remove(gutenberg_file)
    print(f"✅ 一時ファイル削除: {gutenberg_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: deploy.py file.md")
        sys.exit(1)

    try:
        main(sys.argv[1])
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        sys.exit(1)