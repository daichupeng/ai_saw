import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

def init_db():
    """Initialize the database and create necessary tables."""
    db_dir = Path("database")
    db_dir.mkdir(exist_ok=True)
    
    db_path = db_dir / "game.db"
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create raw_prompt_history table with request_id
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS raw_prompt_history (
        prompt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        raw_prompt TEXT NOT NULL,
        raw_response TEXT
    )
    ''')
    
    # Create index on request_id for faster lookups
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_request_id 
    ON raw_prompt_history(request_id)
    ''')
    
    conn.commit()
    conn.close()

def save_prompt_history(raw_prompt: str, raw_response: str, request_id: str) -> int:
    """
    Save a prompt and its response to the database.
    
    Args:
        raw_prompt: The prompt sent to the LLM
        raw_response: The response received from the LLM
        request_id: Unique identifier for this request
        
    Returns:
        int: The prompt_id of the saved record
    """
    db_path = Path("database/game.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO raw_prompt_history (request_id, raw_prompt, raw_response)
    VALUES (?, ?, ?)
    ''', (request_id, raw_prompt, raw_response))
    
    prompt_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return prompt_id

def get_prompt_history(prompt_id: Optional[int] = None, request_id: Optional[str] = None) -> list:
    """
    Retrieve prompt history from the database.
    
    Args:
        prompt_id: Optional specific prompt ID to retrieve
        request_id: Optional specific request ID to retrieve
        
    Returns:
        list: List of tuples containing (prompt_id, request_id, timestamp, raw_prompt, raw_response)
    """
    db_path = Path("database/game.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if prompt_id is not None:
        cursor.execute('''
        SELECT prompt_id, request_id, timestamp, raw_prompt, raw_response
        FROM raw_prompt_history
        WHERE prompt_id = ?
        ''', (prompt_id,))
    elif request_id is not None:
        cursor.execute('''
        SELECT prompt_id, request_id, timestamp, raw_prompt, raw_response
        FROM raw_prompt_history
        WHERE request_id = ?
        ''', (request_id,))
    else:
        cursor.execute('''
        SELECT prompt_id, request_id, timestamp, raw_prompt, raw_response
        FROM raw_prompt_history
        ORDER BY timestamp DESC
        ''')
    
    results = cursor.fetchall()
    conn.close()
    
    return results

def migrate_db():
    """Migrate the database to the new schema with request_id."""
    db_path = Path("database/game.db")
    
    # Backup the old database if it exists
    if db_path.exists():
        backup_path = db_path.with_suffix('.db.bak')
        import shutil
        shutil.copy2(db_path, backup_path)
        
        # Drop the old table and recreate with new schema
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Drop the old table
        cursor.execute('DROP TABLE IF EXISTS raw_prompt_history')
        
        # Create the new table
        cursor.execute('''
        CREATE TABLE raw_prompt_history (
            prompt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            raw_prompt TEXT NOT NULL,
            raw_response TEXT
        )
        ''')
        
        # Create index on request_id
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_request_id 
        ON raw_prompt_history(request_id)
        ''')
        
        conn.commit()
        conn.close()
        
        print(f"Database migrated successfully. Old database backed up to {backup_path}")
    else:
        # If database doesn't exist, just initialize it
        init_db()
        print("New database created with updated schema") 