import requests
import urllib
import pathlib
import os
import subprocess
import threading
import re
import random
import string
import time
import shutil

from telegram.ext import CommandHandler
from telegram import InlineKeyboardMarkup
from fnmatch import fnmatch

from bot import Interval, INDEX_URL, BUTTON_FOUR_NAME, BUTTON_FOUR_URL, BUTTON_FIVE_NAME, BUTTON_FIVE_URL, \
                BUTTON_SIX_NAME, BUTTON_SIX_URL, BLOCK_MEGA_FOLDER, BLOCK_MEGA_LINKS, VIEW_LINK, aria2, \
                dispatcher, DOWNLOAD_DIR, download_dict, download_dict_lock, SHORTENER, SHORTENER_API, \
                TAR_UNZIP_LIMIT, TG_SPLIT_SIZE
from bot.helper.ext_utils import fs_utils, bot_utils
from bot.helper.ext_utils.shortenurl import short_url
from bot.helper.ext_utils.exceptions import DirectDownloadLinkException, NotSupportedExtractionArchive
from bot.helper.mirror_utils.download_utils.aria2_download import AriaDownloadHelper
from bot.helper.mirror_utils.download_utils.mega_downloader import MegaDownloadHelper
from bot.helper.mirror_utils.download_utils.qbit_downloader import QbitTorrent
from bot.helper.mirror_utils.download_utils.direct_link_generator import direct_link_generator
from bot.helper.mirror_utils.download_utils.telegram_downloader import TelegramDownloadHelper
from bot.helper.mirror_utils.status_utils import listeners
from bot.helper.mirror_utils.status_utils.extract_status import ExtractStatus
from bot.helper.mirror_utils.status_utils.tar_status import TarStatus
from bot.helper.mirror_utils.status_utils.split_status import SplitStatus
from bot.helper.mirror_utils.status_utils.upload_status import UploadStatus
from bot.helper.mirror_utils.status_utils.tg_upload_status import TgUploadStatus
from bot.helper.mirror_utils.status_utils.gdownload_status import DownloadStatus
from bot.helper.mirror_utils.upload_utils import gdriveTools, pyrogramEngine
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import *
from bot.helper.telegram_helper import button_build

ariaDlManager = AriaDownloadHelper()
ariaDlManager.start_listener()


class MirrorListener(listeners.MirrorListeners):
    def __init__(self, bot, update, pswd, isTar=False, extract=False, isZip=False, isQbit=False, isLeech=False):
        super().__init__(bot, update)
        self.isTar = isTar
        self.extract = extract
        self.isZip = isZip
        self.isQbit = isQbit
        self.isLeech = isLeech
        self.pswd = pswd

    def onDownloadStarted(self):
        pass

    def onDownloadProgress(self):
        # We are handling this on our own!
        pass

    def clean(self):
        try:
            aria2.purge()
            Interval[0].cancel()
            del Interval[0]
            delete_all_messages()
        except IndexError:
            pass

    def onDownloadComplete(self):
        with download_dict_lock:
            LOGGER.info(f"Download completed: {download_dict[self.uid].name()}")
            download = download_dict[self.uid]
            name = f"{download.name()}".replace('/', '')
            gid = download.gid()
            size = download.size_raw()
            if name == "None" or self.isQbit: # when pyrogram's media.file_name is of NoneType
                name = os.listdir(f'{DOWNLOAD_DIR}{self.uid}')[0]
            m_path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        if self.isTar:
            try:
                with download_dict_lock:
                    download_dict[self.uid] = TarStatus(name, m_path, size)
                if self.isZip:
                    pswd = self.pswd
                    path = m_path + ".zip"
                    LOGGER.info(f'Zip: orig_path: {m_path}, zip_path: {path}')
                    if pswd is not None:
                        subprocess.run(["7z", "a", f"-p{pswd}", path, m_path])
                    else:
                        subprocess.run(["7z", "a", path, m_path])
                else:
                    path = fs_utils.tar(m_path)
            except FileNotFoundError:
                LOGGER.info('File to archive not found!')
                self.onUploadError('Internal error occurred!!')
                return
            try:
                shutil.rmtree(m_path)
            except:
                os.remove(m_path)
        elif self.extract:
            try:
                LOGGER.info(f"Extracting: {name}")
                with download_dict_lock:
                    download_dict[self.uid] = ExtractStatus(name, m_path, size)
                pswd = self.pswd
                if os.path.isdir(m_path):
                    for dirpath, subdir, files in os.walk(m_path, topdown=False):
                        for file in files:
                            suffixes = (".part1.rar", ".part01.rar", ".part001.rar", ".part0001.rar")
                            if (file.endswith(".rar") and "part" not in file) or file.endswith(suffixes):
                                m_path = os.path.join(dirpath, file)
                                if pswd is not None:
                                    result = subprocess.run(["7z", "x", f"-p{pswd}", m_path, f"-o{dirpath}"])
                                else:
                                    result = subprocess.run(["7z", "x", m_path, f"-o{dirpath}"])
                                if result.returncode != 0:
                                    LOGGER.warning('Unable to extract archive!')
                                break
                        for file in files:
                            if file.endswith(".rar") or fnmatch(file, "*.r[0-9]") or fnmatch(file, "*.r[0-9]*"):
                                del_path = os.path.join(dirpath, file)
                                os.remove(del_path)
                    path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
                else:
                    path = fs_utils.get_base_name(m_path)
                    if pswd is not None:
                        result = subprocess.run(["pextract", m_path, pswd])
                    else:
                        result = subprocess.run(["extract", m_path])
                    if result.returncode == 0:
                        os.remove(m_path)
                        LOGGER.info(f"Deleting archive: {m_path}")
                    else:
                        LOGGER.warning('Unable to extract archive! Uploading anyway')
                        path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
                LOGGER.info(f'got path: {path}')

            except NotSupportedExtractionArchive:
                LOGGER.info("Not any valid archive, uploading file as it is.")
                path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        else:
            path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        up_name = pathlib.PurePath(path).name
        up_path = f'{DOWNLOAD_DIR}{self.uid}/{up_name}'
        size = fs_utils.get_path_size(up_path)
        if self.isLeech:
            checked = False
            for dirpath, subdir, files in os.walk(f'{DOWNLOAD_DIR}{self.uid}', topdown=False):
                for file in files:
                    f_path = os.path.join(dirpath, file)
                    f_size = os.path.getsize(f_path)
                    if int(f_size) > TG_SPLIT_SIZE:
                        if not checked:
                            checked = True
                            with download_dict_lock:
                                download_dict[self.uid] = SplitStatus(up_name, up_path, size)
                            LOGGER.info(f"Splitting: {up_name}")
                        fs_utils.split(f_path, f_size, file, dirpath, TG_SPLIT_SIZE)
                        os.remove(f_path)
            LOGGER.info(f"Leech Name: {up_name}")
            tg = pyrogramEngine.TgUploader(up_name, self)
            tg_upload_status = TgUploadStatus(tg, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = tg_upload_status
            update_all_messages()
            tg.upload()
        else:
            LOGGER.info(f"Upload Name: {up_name}")
            drive = gdriveTools.GoogleDriveHelper(up_name, self)
            upload_status = UploadStatus(drive, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = upload_status
            update_all_messages()
            drive.upload(up_name)

    def onDownloadError(self, error):
        error = error.replace('<', ' ')
        error = error.replace('>', ' ')
        with download_dict_lock:
            try:
                download = download_dict[self.uid]
                del download_dict[self.uid]
                fs_utils.clean_download(download.path())
            except Exception as e:
                LOGGER.error(str(e))
            count = len(download_dict)
        if self.message.from_user.username:
            uname = f"@{self.message.from_user.username}"
        else:
            uname = f'<a href="tg://user?id={self.message.from_user.id}">{self.message.from_user.first_name}</a>'
        msg = f"{uname} your download has been stopped due to: {error}"
        sendMessage(msg, self.bot, self.update)
        if count == 0:
            self.clean()
        else:
            update_all_messages()

    def onUploadStarted(self):
        pass

    def onUploadProgress(self):
        pass

    def onUploadComplete(self, link: str, size, files, folders, typ):
        if self.isLeech:
            if self.message.from_user.username:
                uname = f"@{self.message.from_user.username}"
            else:
                uname = f'<a href="tg://user?id={self.message.from_user.id}">{self.message.from_user.first_name}</a>'
            count = len(files)
            if self.message.chat.type == 'private':
                msg = f'<b>Name:</b> <code>{link}</code>\n'
                msg += f'<b>Total Files:</b> {count}'
                sendMessage(msg, self.bot, self.update)
            else:
                chat_id = str(self.message.chat.id)[4:]
                msg = f"<b>Name:</b> <a href='https://t.me/c/{chat_id}/{self.uid}'>{link}</a>\n"
                msg += f'<b>Total Files:</b> {count}\n'
                msg += f'cc: {uname}\n\n'
                fmsg = ''
                for index, item in enumerate(list(files), start=1):
                    msg_id = files[item]
                    link = f"https://t.me/c/{chat_id}/{msg_id}"
                    fmsg += f"{index}. <a href='{link}'>{item}</a>\n"
                    if len(fmsg) > 3900:
                        sendMessage(msg + fmsg, self.bot, self.update)
                        fmsg = ''
                if fmsg != '':
                    sendMessage(msg + fmsg, self.bot, self.update)
            with download_dict_lock:
                try:
                    fs_utils.clean_download(download_dict[self.uid].path())
                except FileNotFoundError:
                    pass
                del download_dict[self.uid]
                count = len(download_dict)
            if count == 0:
                self.clean()
            else:
                update_all_messages()
            return
        with download_dict_lock:
            msg = f'<b>Filename: </b><code>{download_dict[self.uid].name()}</code>\n<b>Size: </b><code>{size}</code>'
            if os.path.isdir(f'{DOWNLOAD_DIR}/{self.uid}/{download_dict[self.uid].name()}'):
                msg += '\n<b>Type: </b><code>Folder</code>'
                msg += f'\n<b>SubFolders: </b><code>{folders}</code>'
                msg += f'\n<b>Files: </b><code>{files}</code>'
            else:
                msg += f'\n<b>Type: </b><code>{typ}</code>'
            buttons = button_build.ButtonMaker()
            if SHORTENER is not None and SHORTENER_API is not None:
                surl = short_url(link)
                buttons.buildbutton("🪔 Drive Link 🪔", surl)
            else:
                buttons.buildbutton("🪔 Drive Link 🪔", link)
            LOGGER.info(f'Done Uploading {download_dict[self.uid].name()}')
            if INDEX_URL is not None:
                url_path = requests.utils.quote(f'{download_dict[self.uid].name()}')
                share_url = f'{INDEX_URL}/{url_path}'
                if os.path.isdir(f'{DOWNLOAD_DIR}/{self.uid}/{download_dict[self.uid].name()}'):
                    share_url += '/'
                    if SHORTENER is not None and SHORTENER_API is not None:
                        siurl = short_url(share_url)
                        buttons.buildbutton("⚡ Index Link 🔰", siurl)
                    else:
                        buttons.buildbutton("⚡ Index Link 🔰", share_url)
                else:
                    share_urls = f'{INDEX_URL}/{url_path}?a=view'
                    if SHORTENER is not None and SHORTENER_API is not None:
                        siurl = short_url(share_url)
                        buttons.buildbutton("⚡ Index Link 🔰", siurl)
                        if VIEW_LINK:
                            siurls = short_url(share_urls)
                            buttons.buildbutton("👸 View Link 👸", siurls)
                    else:
                        buttons.buildbutton(" 🔰 Index Link 🔰", share_url)
                        if VIEW_LINK:
                            buttons.buildbutton("👸 View Link 👸", share_urls)
            if BUTTON_FOUR_NAME is not None and BUTTON_FOUR_URL is not None:
                buttons.buildbutton(f"{BUTTON_FOUR_NAME}", f"{BUTTON_FOUR_URL}")
            if BUTTON_FIVE_NAME is not None and BUTTON_FIVE_URL is not None:
                buttons.buildbutton(f"{BUTTON_FIVE_NAME}", f"{BUTTON_FIVE_URL}")
            if BUTTON_SIX_NAME is not None and BUTTON_SIX_URL is not None:
                buttons.buildbutton(f"{BUTTON_SIX_NAME}", f"{BUTTON_SIX_URL}")
            if self.message.from_user.username:
                uname = f"@{self.message.from_user.username}"
            else:
                uname = f'<a href="tg://user?id={self.message.from_user.id}">{self.message.from_user.first_name}</a>'
            if uname is not None:
                msg += f'\n\nMirror BY 👉 :💃: {uname}'
            try:
                fs_utils.clean_download(download_dict[self.uid].path())
            except FileNotFoundError:
                pass
            del download_dict[self.uid]
            count = len(download_dict)
        sendMarkup(msg, self.bot, self.update, InlineKeyboardMarkup(buttons.build_menu(2)))
        if count == 0:
            self.clean()
        else:
            update_all_messages()

    def onUploadError(self, error):
        e_str = error.replace('<', '').replace('>', '')
        with download_dict_lock:
            try:
                fs_utils.clean_download(download_dict[self.uid].path())
            except FileNotFoundError:
                pass
            del download_dict[self.message.message_id]
            count = len(download_dict)
        if self.message.from_user.username:
            uname = f"@{self.message.from_user.username}"
        else:
            uname = f'<a href="tg://user?id={self.message.from_user.id}">{self.message.from_user.first_name}</a>'
        if uname is not None:
            men = f'{uname} '
        sendMessage(men + e_str, self.bot, self.update)
        if count == 0:
            self.clean()
        else:
            update_all_messages()

def _mirror(bot, update, isTar=False, extract=False, isZip=False, isQbit=False, isLeech=False):
    mesg = update.message.text.split('\n')
    message_args = mesg[0].split(' ')
    name_args = mesg[0].split('|')
    qbitsel = False
    try:
        link = message_args[1]
        if link == "s":
            qbitsel = True
            link = message_args[2]
        if link.startswith("|") or link.startswith("pswd: "):
            link = ''
    except IndexError:
        link = ''
    try:
        name = name_args[1]
        name = name.strip()
        if name.startswith("pswd: "):
            name = ''
    except IndexError:
        name = ''
    try:
        ussr = urllib.parse.quote(mesg[1], safe='')
        pssw = urllib.parse.quote(mesg[2], safe='')
    except:
        ussr = ''
        pssw = ''
    if ussr != '' and pssw != '':
        link = link.split("://", maxsplit=1)
        link = f'{link[0]}://{ussr}:{pssw}@{link[1]}'
    pswd = re.search('(?<=pswd: )(.*)', update.message.text)
    if pswd is not None:
      pswd = pswd.groups()
      pswd = " ".join(pswd)
    if link != '':
        LOGGER.info(link)
    link = link.strip()
    reply_to = update.message.reply_to_message
    if reply_to is not None:
        file = None
        media_array = [reply_to.document, reply_to.video, reply_to.audio]
        for i in media_array:
            if i is not None:
                file = i
                break
        if (
            not bot_utils.is_url(link)
            and not bot_utils.is_magnet(link)
            or len(link) == 0
        ):
            if file is None:
                reply_text = reply_to.text
                reply_text = re.split('\n ', reply_text)[0]
                if bot_utils.is_url(reply_text) or bot_utils.is_magnet(reply_text):
                    link = reply_text

            elif isQbit:
                file_name = str(time.time()).replace(".", "") + ".torrent"
                file.get_file().download(custom_path=f"{file_name}")
                link = f"{file_name}"
            elif file.mime_type != "application/x-bittorrent":
                listener = MirrorListener(bot, update, pswd, isTar, extract, isZip, isLeech=isLeech)
                tg_downloader = TelegramDownloadHelper(listener)
                ms = update.message
                tg_downloader.add_download(ms, f'{DOWNLOAD_DIR}{listener.uid}/', name)
                return
            else:
                link = file.get_file().file_path
    if bot_utils.is_url(link) and not bot_utils.is_magnet(link) and not os.path.exists(link) and isQbit:
        resp = requests.get(link)
        if resp.status_code == 200:
            file_name = str(time.time()).replace(".", "") + ".torrent"
            open(file_name, "wb").write(resp.content)
            link = f"{file_name}"
        else:
            sendMessage("ERROR: link got HTTP response:" + resp.status_code, bot, update)
            return

    elif not bot_utils.is_url(link) and not bot_utils.is_magnet(link):
        sendMessage('No download source provided', bot, update)
        return
    elif not os.path.exists(link) and not bot_utils.is_mega_link(link) and not bot_utils.is_gdrive_link(link) and not bot_utils.is_magnet(link):
        try:
            link = direct_link_generator(link)
        except DirectDownloadLinkException as e:
            LOGGER.info(e)
            if "ERROR:" in str(e):
                sendMessage(f"{e}", bot, update)
                return
            if "Youtube" in str(e):
                sendMessage(f"{e}", bot, update)
                return

    listener = MirrorListener(bot, update, pswd, isTar, extract, isZip, isQbit, isLeech)

    if bot_utils.is_gdrive_link(link):
        if not isTar and not extract and not isLeech:
            sendMessage(f"Use /{BotCommands.CloneCommand} to clone Google Drive file/folder\nUse /{BotCommands.TarMirrorCommand} to make tar of Google Drive folder\nUse /{BotCommands.UnzipMirrorCommand} to extracts archive Google Drive file", bot, update)
            return
        res, size, name, files = gdriveTools.GoogleDriveHelper().clonehelper(link)
        if res != "":
            sendMessage(res, bot, update)
            return
        if TAR_UNZIP_LIMIT is not None:
            result = bot_utils.check_limit(size, TAR_UNZIP_LIMIT)
            if result:
                msg = f'Failed, Tar/Unzip limit is {TAR_UNZIP_LIMIT}.\nYour File/Folder size is {get_readable_file_size(size)}.'
                sendMessage(msg, bot, update)
                return
        LOGGER.info(f"Download Name : {name}")
        drive = gdriveTools.GoogleDriveHelper(name, listener)
        gid = ''.join(random.SystemRandom().choices(string.ascii_letters + string.digits, k=12))
        download_status = DownloadStatus(drive, size, listener, gid)
        with download_dict_lock:
            download_dict[listener.uid] = download_status
        sendStatusMessage(update, bot)
        drive.download(link)

    elif bot_utils.is_mega_link(link):
        if BLOCK_MEGA_LINKS:
            sendMessage("Mega links are blocked!", bot, update)
            return
        link_type = bot_utils.get_mega_link_type(link)
        if link_type == "folder" and BLOCK_MEGA_FOLDER:
            sendMessage("Mega folder are blocked!", bot, update)
        else:
            mega_dl = MegaDownloadHelper()
            mega_dl.add_download(link, f'{DOWNLOAD_DIR}{listener.uid}/', listener)

    elif isQbit and (bot_utils.is_magnet(link) or os.path.exists(link)):
        qbit = QbitTorrent()
        qbit.add_torrent(link, f'{DOWNLOAD_DIR}{listener.uid}/', listener, qbitsel)

    else:
        ariaDlManager.add_download(link, f'{DOWNLOAD_DIR}{listener.uid}/', listener, name)
        sendStatusMessage(update, bot)


def mirror(update, context):
    _mirror(context.bot, update)

def tar_mirror(update, context):
    _mirror(context.bot, update, True)

def unzip_mirror(update, context):
    _mirror(context.bot, update, extract=True)

def zip_mirror(update, context):
    _mirror(context.bot, update, True, isZip=True)

def qb_mirror(update, context):
    _mirror(context.bot, update, isQbit=True)

def qb_tar_mirror(update, context):
    _mirror(context.bot, update, True, isQbit=True)

def qb_unzip_mirror(update, context):
    _mirror(context.bot, update, extract=True, isQbit=True)

def qb_zip_mirror(update, context):
    _mirror(context.bot, update, True, isZip=True, isQbit=True)

def leech(update, context):
    _mirror(context.bot, update, isLeech=True)

def tar_leech(update, context):
    _mirror(context.bot, update, True, isLeech=True)

def unzip_leech(update, context):
    _mirror(context.bot, update, extract=True, isLeech=True)

def zip_leech(update, context):
    _mirror(context.bot, update, True, isZip=True, isLeech=True)

def qb_leech(update, context):
    _mirror(context.bot, update, isQbit=True, isLeech=True)

def qb_tar_leech(update, context):
    _mirror(context.bot, update, True, isQbit=True, isLeech=True)

def qb_unzip_leech(update, context):
    _mirror(context.bot, update, extract=True, isQbit=True, isLeech=True)

def qb_zip_leech(update, context):
    _mirror(context.bot, update, True, isZip=True, isQbit=True, isLeech=True)

mirror_handler = CommandHandler(BotCommands.MirrorCommand, mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
tar_mirror_handler = CommandHandler(BotCommands.TarMirrorCommand, tar_mirror,
                                    filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
unzip_mirror_handler = CommandHandler(BotCommands.UnzipMirrorCommand, unzip_mirror,
                                      filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
zip_mirror_handler = CommandHandler(BotCommands.ZipMirrorCommand, zip_mirror,
                                    filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_mirror_handler = CommandHandler(BotCommands.QbMirrorCommand, qb_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_tar_mirror_handler = CommandHandler(BotCommands.QbTarMirrorCommand, qb_tar_mirror,
                                    filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_unzip_mirror_handler = CommandHandler(BotCommands.QbUnzipMirrorCommand, qb_unzip_mirror,
                                      filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_zip_mirror_handler = CommandHandler(BotCommands.QbZipMirrorCommand, qb_zip_mirror,
                                    filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
leech_handler = CommandHandler(BotCommands.LeechCommand, leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
tar_leech_handler = CommandHandler(BotCommands.TarLeechCommand, tar_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
unzip_leech_handler = CommandHandler(BotCommands.UnzipLeechCommand, unzip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
zip_leech_handler = CommandHandler(BotCommands.ZipLeechCommand, zip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_leech_handler = CommandHandler(BotCommands.QbLeechCommand, qb_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_tar_leech_handler = CommandHandler(BotCommands.QbTarLeechCommand, qb_tar_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_unzip_leech_handler = CommandHandler(BotCommands.QbUnzipLeechCommand, qb_unzip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_zip_leech_handler = CommandHandler(BotCommands.QbZipLeechCommand, qb_zip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
dispatcher.add_handler(mirror_handler)
dispatcher.add_handler(tar_mirror_handler)
dispatcher.add_handler(unzip_mirror_handler)
dispatcher.add_handler(zip_mirror_handler)
dispatcher.add_handler(qb_mirror_handler)
dispatcher.add_handler(qb_tar_mirror_handler)
dispatcher.add_handler(qb_unzip_mirror_handler)
dispatcher.add_handler(qb_zip_mirror_handler)
dispatcher.add_handler(leech_handler)
dispatcher.add_handler(tar_leech_handler)
dispatcher.add_handler(unzip_leech_handler)
dispatcher.add_handler(zip_leech_handler)
dispatcher.add_handler(qb_leech_handler)
dispatcher.add_handler(qb_tar_leech_handler)
dispatcher.add_handler(qb_unzip_leech_handler)
dispatcher.add_handler(qb_zip_leech_handler)
