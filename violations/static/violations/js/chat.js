// Staff/Faculty realtime chat (WebSocket)
(function(){
  // Support both legacy id `chatToggle` and current header button id `chatHeaderBtn`.
  const chatToggle = document.getElementById('chatToggle') || document.getElementById('chatHeaderBtn');
  const chatPanel = document.getElementById('chatPanel');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const chatFeed = document.getElementById('chatFeed');

  if(!chatPanel || !chatFeed) return;

  function openPanel(){ chatPanel.classList.add('show'); }
  function closePanel(){ chatPanel.classList.remove('show'); }
  if(chatToggle){ chatToggle.addEventListener('click', () => { chatPanel.classList.toggle('show'); unreadCount = 0; updateBadge(); }); }

  // Build ws:// or wss:// URL
  const room = 'staff-faculty';
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${scheme}://${window.location.host}/ws/chat/${room}/`;

  let socket;
  let reconnectAttempts = 0;
  let unreadCount = 0;

  // Optional unread badge on the header icon
  function updateBadge(){
    if(!chatToggle) return;
    let badge = chatToggle.querySelector('.chat-unread-badge');
    if(unreadCount > 0 && !chatPanel.classList.contains('show')){
      if(!badge){
        badge = document.createElement('span');
        badge.className = 'chat-unread-badge';
        badge.style.cssText = 'position:absolute; top:2px; right:2px; background:#dc2626; color:#fff; font-size:11px; padding:2px 5px; border-radius:12px; line-height:1;';
        chatToggle.style.position = 'relative';
        chatToggle.appendChild(badge);
      }
      badge.textContent = unreadCount > 9 ? '9+' : String(unreadCount);
    } else if(badge) {
      badge.remove();
    }
  }
  function connect(){
    socket = new WebSocket(wsUrl);
    socket.onopen = () => {
      reconnectAttempts = 0;
      appendSystem('Connected to chat');
    };
    socket.onmessage = (ev) => {
      try { var data = JSON.parse(ev.data); } catch { return; }
      if(data.kind === 'system') {
        appendSystem(data.message);
      } else if (data.kind === 'history') {
        // array of {user, message, ts}
        (data.messages || []).forEach(m => appendMessage(m.user, m.message, null, m.ts));
      } else if (data.kind === 'message') {
        appendMessage(data.user, data.message, data.role, data.ts);
        if(!chatPanel.classList.contains('show')){ unreadCount++; updateBadge(); }
      }
    };
    socket.onclose = () => {
      // exponential backoff up to 30s
      const timeout = Math.min(30000, 1500 * Math.pow(2, reconnectAttempts));
      reconnectAttempts++;
      appendSystem('Disconnected. Reconnecting in ' + Math.round(timeout/1000) + 's …');
      setTimeout(connect, timeout);
    };
    socket.onerror = () => { /* handled by onclose */ };
  }
  connect();

  function appendSystem(text){
    const li = document.createElement('li');
    li.className = 'system';
    li.textContent = text;
    chatFeed.appendChild(li);
    chatFeed.scrollTop = chatFeed.scrollHeight;
  }

  function appendMessage(user, text, role, ts){
    const li = document.createElement('li');
    li.className = 'msg';
    const meta = document.createElement('div');
    meta.className = 'meta';
    // include timestamp if available
    let timeText = '';
    try { if(ts) timeText = ' · ' + new Date(ts).toLocaleTimeString(); } catch(e) { timeText = ''; }
    meta.textContent = `${user}${role ? ' • ' + role.replace('_',' ') : ''}${timeText}`;
    const body = document.createElement('div');
    body.className = 'body';
    body.textContent = text;
    li.appendChild(meta);
    li.appendChild(body);
    chatFeed.appendChild(li);
    chatFeed.scrollTop = chatFeed.scrollHeight;
  }

  if(chatForm){
    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = (chatInput?.value || '').trim();
      if(!text || !socket || socket.readyState !== 1) return;
      socket.send(JSON.stringify({ message: text }));
      chatInput.value = '';
      chatInput.focus();
    })
  }
})();
