chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "saveToVault",
    title: "Save to Knowledge Vault 🚀",
    contexts: ["selection", "page", "link", "image"]
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "saveToVault") {
    const selectedText = info.selectionText || "";
    const imageUrl = info.srcUrl || "";
    const pageUrl = info.linkUrl || info.pageUrl || tab.url;

    // Automatically extract post text from LinkedIn page DOM
    let postContextText = "";
    try {
      const [result] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          const selection = window.getSelection().toString();
          if (selection) return selection;

          // Search active LinkedIn post container for text/caption
          const postTextElements = document.querySelectorAll('.feed-shared-update-v2, .update-components-text, .feed-shared-inline-show-more-text');
          for (let el of postTextElements) {
            if (el.innerText && el.innerText.length > 15) {
              return el.innerText;
            }
          }
          return document.title;
        }
      });
      postContextText = result?.result || "";
    } catch (e) {
      postContextText = tab.title || "";
    }

    const formData = new FormData();

    // Construct rich text payload
    let textPayload = `Source URL: ${pageUrl}\n`;
    if (selectedText || postContextText) {
      textPayload += `Post Context & Caption:\n${selectedText || postContextText}\n`;
    }

    formData.append('text', textPayload);

    // Send image_url as separate form parameter for Gemini Vision
    if (imageUrl) {
      formData.append('image_url', imageUrl);
    }

    const BACKEND_URL = 'https://knowledge-vault-backend-m4aj.onrender.com/upload';

    try {
      const response = await fetch(BACKEND_URL, {
        method: 'POST',
        body: formData
      });

      const data = await response.json();

      if (response.ok) {
        console.log('✅ Successfully saved & classified in Vault:', data.path);
      } else {
        console.error('❌ Upload failed:', data.detail);
      }
    } catch (err) {
      console.error('❌ Network error:', err.message);
    }
  }
});