chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "saveToVault",
    title: "Save to Knowledge Vault 🚀",
    contexts: ["selection", "page", "link", "image"] // Added image support
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "saveToVault") {
    const selectedText = info.selectionText || "";
    const imageUrl = info.srcUrl || "";
    const pageUrl = info.linkUrl || info.pageUrl || tab.url;
    const pageTitle = tab.title || "LinkedIn Saved Resource";

    let payloadText = `URL: ${pageUrl}\nTitle: ${pageTitle}\n\n`;

    if (imageUrl) {
      payloadText += `Image URL: ${imageUrl}\n\nContent:\nSaved image resource from LinkedIn.`;
    } else if (selectedText) {
      payloadText += `Content:\n${selectedText}`;
    } else {
      payloadText += `Content:\nArchived link: ${pageUrl}`;
    }

    try {
      const formData = new FormData();
      formData.append('text', payloadText);

      const response = await fetch('https://knowledge-vault-backend-m4aj.onrender.com/upload', {
        method: 'POST',
        body: formData
      });
        
        

      const data = await response.json();

      if (response.ok) {
        console.log('✅ Successfully saved to Vault:', data.path);
      } else {
        console.error('❌ Upload failed:', data.detail);
      }
    } catch (err) {
      console.error('❌ Network error:', err.message);
    }
  }
});