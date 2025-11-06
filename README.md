# 📨 MTA-based ActivityPub Framework
**MTAベースの分散SNS通信基盤**  
Postfix + Dovecot + LMTP を活用し、ActivityPub メッセージを「メール伝送」で処理する新しい分散SNS基盤です。  
HTTPではなく **SMTP/LMTPをIPC（プロセス間通信）として再利用**し、フォロー・投稿・返信をMTAキューで管理します。

---

## 🌐 概要
このプロジェクトは、**電子メール（MTA）をActivityPubメッセージの伝送層として使う**  
新しい分散SNSの通信基盤です。

- 各ノードが **「メールボックス＝Inbox/Outbox」** を持ちます  
- ActivityPub メッセージを SMTP / LMTP で配送  
- MTAキューを活用して **非同期・再送制御・スパム対策** を自動適用  
- すべてのノードは Postfix / Dovecot / LMTP に準拠した構成で相互通信可能  

---

## 🧩 アーキテクチャ
```mermaid
graph TD
  subgraph Mail_Transport
    A[Postfix] --> B[Dovecot LMTP]
    B --> C[[activitypub-lmtp.py]]
    B --> D[[activitypub_lmtp_server.py]]
  end

  subgraph Application
    C --> E[Flask Web UI (app.py)]
    D --> E
    E --> F[inbox.json]
    E --> G[outbox.json]
    E --> H[messages.json]
  end

  subgraph External
    I[Remote Actor (example.com)]
  end

  I -->|Follow| A
  C -->|Accept| I
  E -->|Create(Post)| I
```
