#!/usr/bin/env python3
"""
設定管理モジュール
環境変数から設定を読み込み、デフォルト値を提供する
"""

import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

@dataclass
class Config:
    """WordPress公開設定"""
    server_user: str
    server_host: str
    ssh_port: int
    ssh_key: str
    wp_path: str
    wp_cli: str
    tmp_dir: str
    post_status: str
    use_highlight_code_block: bool

def load_config(config_file: Optional[str] = None) -> Config:
    """
    設定を環境変数から読み込み
    
    Args:
        config_file: .envファイルのパス（指定しない場合は標準の.envを使用）
        
    Returns:
        Config: 設定オブジェクト
        
    Raises:
        ValueError: 必須環境変数が未設定の場合
    """
    load_dotenv(config_file)
    
    # 必須環境変数のチェック
    required_vars = ['WP_SERVER_USER', 'WP_SERVER_HOST', 'WP_SSH_KEY', 'WP_PATH']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        raise ValueError(f"必須環境変数が設定されていません: {', '.join(missing_vars)}")
    
    return Config(
        server_user=os.getenv('WP_SERVER_USER'),
        server_host=os.getenv('WP_SERVER_HOST'), 
        ssh_port=int(os.getenv('WP_SSH_PORT', '22')),
        ssh_key=os.getenv('WP_SSH_KEY'),
        wp_path=os.getenv('WP_PATH'),
        wp_cli=os.getenv('WP_CLI', '~/bin/wp/wp-cli.phar'),
        tmp_dir=os.getenv('WP_TMP_DIR', 'tmp'),
        post_status=os.getenv('WP_POST_STATUS', 'draft'),
        use_highlight_code_block=os.getenv('WP_USE_HIGHLIGHT_CODE_BLOCK', 'True').lower() == 'true'
    )

def validate_config(config: Config) -> None:
    """
    設定の妥当性をチェック
    
    Args:
        config: 設定オブジェクト
        
    Raises:
        ValueError: 設定が無効な場合
    """
    if not os.path.exists(config.ssh_key):
        raise ValueError(f"SSH鍵ファイルが見つかりません: {config.ssh_key}")
        
    if config.ssh_port < 1 or config.ssh_port > 65535:
        raise ValueError(f"無効なSSHポート番号: {config.ssh_port}")
        
    valid_statuses = ['draft', 'publish', 'private', 'pending']
    if config.post_status not in valid_statuses:
        raise ValueError(f"無効な投稿ステータス: {config.post_status}. 有効な値: {valid_statuses}")

def get_config() -> Config:
    """
    設定を取得し、バリデーションを実行
    
    Returns:
        Config: 検証済み設定オブジェクト
    """
    config = load_config()
    validate_config(config)
    return config
