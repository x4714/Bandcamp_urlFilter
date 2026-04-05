import base64
import hashlib

import streamlit as st

QOBUZ_HELP_SALT = b"bandcamp-qobuz-token-help-v2"
QOBUZ_HELP_SHA256 = "c8aba37d28cf92ed28cffb63a2c72d36a04e33bc04b6718be5a3c7a2531c97f7"
QOBUZ_HELP_ENCRYPTED_TEXT = (
    "aA39JyYzqRklVNNIjt2zUQnZYc3J4LIsKtvkhT2HlW-zC-Q13AmAk-lUSCx9ropxlOeXku-Vkd1N21qtd7leWqrR-atFMwszMOVH"
    "Tec0C0AGwQKtZEGN3J3-U3RcWrzWJWhj4mxKpRBpczYlnfOHw8ukH52DSZCWR4XdscUV8T01Y-BzOf9yKSrro9gPRk3ygUk6fHQM"
    "s5kvBmNAcqzJ-Zw9b3CROdVKiX7tRu7fi9ZYNmNLOWLo9pn1vssMdPftaYIEQkUX6CrmGI0owriUZnefwkmTV-hPod1usONRk8FVp"
    "B9V57eQ5QafIGzuasjNIAqS0C2Lbgeo_Ac8ZImSrXXuR_gk6zdkbOqrnej6DDSn0f694MIvZOdrvGj33lQ1qReW2Tr-7IIxgtpmt"
    "EcqoUI1JJXIl6lioM6IqiGtPOCP-26ygyJoSLO4OkZx5xZxMw6ghdnFGY_MKULdGOfXm3B0HfAMwlA8ulaPq11uT2l8Oxbxd-F_hh"
    "DWZWxLMcnbMHXkRPvwRuTvPQuG-AYGsEKnSnm7PcCVOoNiWp2376MwQ4U-qoslIlikFG_Vhd9rmVmUh7H29wjmtsbybT8_gM-ijb"
    "r4_VqjAyCWAvWgmwS0oW0jAB9tg28jw0V8sp0dBKObZAEpHK4s7ZJJn6m9QRghP-yhHnXyVu2dq2WOK620iGar5c7hLuh09fZaa1Q"
    "ek8JTu8QNwgfy7NWsdXugXHpW9kTxigSuX8pJ1pcRE4RPLzinRqfoO0-NusiF1qcCEaRvKqQq4aDHM3_LbImgRN3gsZsqN6hKO0kU"
    "fmzfFMhDaCOgatV0nd23505O2Til0-3t_r3FvzLsDoyhugKP2HQIsax8pEdi5v4HEs9_I0xAlgeFmkkqtZi5n9II4JgjyPhIOIHy"
    "ekMWXPFOydNzb94AjFayqnTdNWdPFujOE6hCStnoSImR-tXFlLi2ZyImNc33gc_FzfDtNGxx_vz-GFNOYXU1zRvOYYMH3qUwhWY9"
    "qk_QWQjwmE_0Cufvf9HhwnMccAFtDJA949rxVwTLA1WJt4vPCotaWxjPFZjbTHrZWVtfWoU5LSYNJdfdrw=="
)


def render_modal_base_styles() -> None:
    st.markdown(
        """
        <style>
        div[data-baseweb="modal"] {
            inset: 0 !important;
            background: rgba(0, 0, 0, 0.7);
        }
        div[data-baseweb="modal"] > div {
            background: rgba(0, 0, 0, 0.7) !important;
        }
        div[role="presentation"][data-testid*="overlay"] {
            background: rgba(0, 0, 0, 0.7) !important;
        }
        div[data-testid="stDialog"] div[role="dialog"] {
            position: fixed !important;
            inset: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            margin: 0 !important;
            border-radius: 0 !important;
            padding: 0 !important;
            background: transparent !important;
        }
        div[data-testid="stDialog"] div[role="dialog"] > div {
            height: 100vh !important;
            padding: 1rem 1.25rem !important;
        }
        div[data-testid="stDialog"] [data-testid="stDialogHeader"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_qobuz_help_state() -> None:
    if "qobuz_token_help_passphrase_open" not in st.session_state:
        st.session_state.qobuz_token_help_passphrase_open = False
    if "qobuz_token_help_content_open" not in st.session_state:
        st.session_state.qobuz_token_help_content_open = False
    if "qobuz_token_help_text" not in st.session_state:
        st.session_state.qobuz_token_help_text = ""
    if "qobuz_token_help_error" not in st.session_state:
        st.session_state.qobuz_token_help_error = ""


def open_qobuz_help_modal() -> None:
    st.session_state.qobuz_token_help_error = ""
    st.session_state.qobuz_token_help_passphrase_open = True
    st.session_state.qobuz_token_help_content_open = False


def _decrypt_qobuz_help_text(passphrase: str) -> str:
    encrypted = base64.urlsafe_b64decode(QOBUZ_HELP_ENCRYPTED_TEXT.encode("utf-8"))
    key = hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        QOBUZ_HELP_SALT,
        200000,
        dklen=len(encrypted),
    )
    decrypted = bytes(a ^ b for a, b in zip(encrypted, key))
    return decrypted.decode("utf-8")


def _is_valid_qobuz_help_text(text: str) -> bool:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest == QOBUZ_HELP_SHA256


def _open_dialog(title: str):
    dialog_api = getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None)
    if dialog_api is None:
        return None
    return dialog_api(title)


def _apply_modal_runtime_patch(passphrase_mode: bool = False) -> None:
    mode_js = "true" if passphrase_mode else "false"
    st.iframe(
        """
        <script>
        const passphraseMode = __PASSMODE__;
        const patchModal = () => {
          const doc = window.parent.document;
          const isVisible = (el) => {
            if (!el) return false;
            const style = window.parent.getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
          };

          const overlays = [
            ...doc.querySelectorAll('div[data-baseweb="modal"]'),
            ...doc.querySelectorAll('div[role="presentation"][data-testid*="overlay"]')
          ];
          overlays.forEach((el) => {
            el.style.background = 'rgba(0, 0, 0, 0.7)';
          });

          const dialogs = doc.querySelectorAll('div[data-testid="stDialog"] div[role="dialog"]');
          dialogs.forEach((el) => {
            el.style.setProperty('display', 'flex', 'important');
            el.style.setProperty('align-items', 'flex-start', 'important');
            el.style.setProperty('justify-content', 'center', 'important');
          });

          const panes = doc.querySelectorAll('div[data-testid="stDialog"] div[role="dialog"] > div');
          panes.forEach((el) => {
            el.style.setProperty('margin', '0', 'important');
            el.style.setProperty('overflow-y', 'auto', 'important');
            el.scrollTop = 0;
          });

          doc.querySelectorAll('div[data-testid="stLayoutWrapper"][data-passphrase-shift="1"]').forEach((el) => {
            el.style.removeProperty('margin-top');
            el.removeAttribute('data-passphrase-shift');
          });
          if (!passphraseMode) {
            return;
          }

          const passphraseSelector = 'input[aria-label="Passphrase"], input[placeholder="Enter passphrase..."]';
          const activePassphraseDialogs = Array.from(dialogs).filter((dialogEl) => {
            if (!isVisible(dialogEl)) return false;
            const input = dialogEl.querySelector(passphraseSelector);
            return isVisible(input);
          });

          dialogs.forEach((dialogEl) => {
            if (!activePassphraseDialogs.includes(dialogEl)) {
              const block = dialogEl.querySelector('div[data-testid="stVerticalBlock"]');
              const layoutWrappers = dialogEl.querySelectorAll('div[data-testid="stLayoutWrapper"]');
              if (block) {
                block.style.removeProperty('position');
                block.style.removeProperty('margin-top');
                block.style.removeProperty('width');
                block.style.removeProperty('max-width');
                block.style.removeProperty('z-index');
              }
              layoutWrappers.forEach((el) => el.style.removeProperty('margin-top'));
            }
          });

          if (activePassphraseDialogs.length > 0) {
            activePassphraseDialogs.forEach((dialogForPassphrase) => {
              const inputEl = dialogForPassphrase.querySelector(passphraseSelector);
              if (!isVisible(inputEl)) return;

              inputEl.setAttribute('type', 'text');
              inputEl.setAttribute('autocomplete', 'off');
              inputEl.setAttribute('autocorrect', 'off');
              inputEl.setAttribute('autocapitalize', 'off');
              inputEl.setAttribute('spellcheck', 'false');
              inputEl.style.webkitTextSecurity = 'disc';

              dialogForPassphrase.style.setProperty('display', 'flex', 'important');
              dialogForPassphrase.style.setProperty('align-items', 'center', 'important');
              dialogForPassphrase.style.setProperty('justify-content', 'center', 'important');

              const activePane = dialogForPassphrase.firstElementChild;
              if (activePane) {
                activePane.style.setProperty('display', 'grid', 'important');
                activePane.style.setProperty('place-items', 'center', 'important');
                activePane.style.setProperty('text-align', 'center', 'important');
                activePane.style.setProperty('height', '100vh', 'important');
              }

              const centerBlock = inputEl.closest('div[data-testid="stVerticalBlock"]');
              if (centerBlock) {
                centerBlock.style.setProperty('position', 'relative', 'important');
                centerBlock.style.setProperty('width', 'min(92vw, 460px)', 'important');
                centerBlock.style.setProperty('max-width', '92vw', 'important');
                centerBlock.style.setProperty('z-index', '1001', 'important');

                const firstLayoutWrapper = centerBlock.closest('div[data-testid="stLayoutWrapper"]');
                const secondLayoutWrapper = firstLayoutWrapper
                  ? firstLayoutWrapper.parentElement?.closest('div[data-testid="stLayoutWrapper"]')
                  : null;
                if (secondLayoutWrapper) {
                  secondLayoutWrapper.style.setProperty('margin-top', '50%', 'important');
                  secondLayoutWrapper.setAttribute('data-passphrase-shift', '1');
                } else if (firstLayoutWrapper) {
                  firstLayoutWrapper.style.setProperty('margin-top', '50%', 'important');
                  firstLayoutWrapper.setAttribute('data-passphrase-shift', '1');
                }
              }
            });
          }
        };

        patchModal();
        setTimeout(patchModal, 50);
        setTimeout(patchModal, 250);
        const patchUntil = Date.now() + 4000;
        const timer = setInterval(() => {
          patchModal();
          if (Date.now() > patchUntil) clearInterval(timer);
        }, 120);
        </script>
        """.replace("__PASSMODE__", mode_js),
        height=1,
    )


def _render_qobuz_passphrase_modal() -> None:
    dialog = _open_dialog("\u200b")
    if dialog is None:
        st.error("This Streamlit version does not support modal dialogs.")
        st.session_state.qobuz_token_help_passphrase_open = False
        return

    @dialog
    def _modal() -> None:
        _apply_modal_runtime_patch(passphrase_mode=True)
        st.subheader("Enter Passphrase")
        st.caption("Passphrase is required to decrypt and show the guide.")
        if st.session_state.qobuz_token_help_error:
            st.error(st.session_state.qobuz_token_help_error)

        with st.form("qobuz_unlock_form", clear_on_submit=False):
            passphrase = st.text_input(
                "Passphrase",
                type="default",
                key="qobuz_token_passphrase_input",
                autocomplete="off",
                placeholder="Enter passphrase...",
                label_visibility="collapsed",
            )
            unlock_btn = st.form_submit_button("Unlock", type="primary", use_container_width=True)
        cancel_btn = st.button("Cancel", use_container_width=True)

        if unlock_btn:
            with st.spinner("Decrypting..."):
                try:
                    decrypted_text = _decrypt_qobuz_help_text(passphrase)
                    if _is_valid_qobuz_help_text(decrypted_text):
                        st.session_state.qobuz_token_help_text = decrypted_text
                        st.session_state.qobuz_token_help_error = ""
                        st.session_state.qobuz_token_help_passphrase_open = False
                        st.session_state.qobuz_token_help_content_open = True
                        st.rerun()
                    else:
                        st.session_state.qobuz_token_help_error = "Incorrect passphrase."
                except Exception:
                    st.session_state.qobuz_token_help_error = "Incorrect passphrase."
            st.rerun()

        if cancel_btn:
            st.session_state.qobuz_token_help_error = ""
            st.session_state.qobuz_token_help_passphrase_open = False
            st.rerun()

    _modal()


def _render_qobuz_content_modal() -> None:
    dialog = _open_dialog("\u200b")
    if dialog is None:
        st.error("This Streamlit version does not support modal dialogs.")
        st.session_state.qobuz_token_help_content_open = False
        return

    @dialog
    def _modal() -> None:
        _apply_modal_runtime_patch(passphrase_mode=False)
        st.markdown(st.session_state.qobuz_token_help_text or "_No guide text available._")
        close_btn = st.button("Close", use_container_width=True)
        if close_btn:
            st.session_state.qobuz_token_help_content_open = False
            st.rerun()

    _modal()


def render_qobuz_help_modals() -> None:
    if st.session_state.qobuz_token_help_passphrase_open:
        _render_qobuz_passphrase_modal()
    if st.session_state.qobuz_token_help_content_open:
        _render_qobuz_content_modal()
