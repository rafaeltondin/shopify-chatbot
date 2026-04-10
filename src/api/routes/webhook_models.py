# -*- coding: utf-8 -*-
"""
Webhook Models para Evolution API v2
Compatível com payloads v1 e v2 da Evolution API
"""
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Optional, Any, Literal, Dict, Union, List
import base64


def convert_byte_dict_to_base64(value: Any) -> Optional[str]:
    """
    Converte um dict de bytes (formato Evolution API v2) para string base64.

    Evolution API v2 envia dados binários como:
    {"0": 239, "1": 56, "2": 158, ...}

    Esta função converte para base64 string.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        try:
            # Ordenar pelas chaves numéricas e extrair os valores
            max_index = max(int(k) for k in value.keys())
            byte_array = bytes([value[str(i)] for i in range(max_index + 1)])
            return base64.b64encode(byte_array).decode('utf-8')
        except (ValueError, KeyError, TypeError):
            # Se falhar, retorna None
            return None
    return None


def convert_file_length(value: Any) -> Optional[int]:
    """
    Converte fileLength do formato Evolution API v2 para int.

    Evolution API v2 envia como:
    {"low": 12499, "high": 0, "unsigned": true}

    ou como string/int diretamente.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        # Formato v2: {"low": N, "high": M, "unsigned": bool}
        # Para arquivos normais, "high" é 0 e o valor real está em "low"
        low = value.get('low', 0)
        high = value.get('high', 0)
        if high == 0:
            return low
        # Para valores muito grandes (improvável para mídia)
        return (high << 32) | low
    return None

class WebhookMessageKey(BaseModel):
    remoteJid: str
    fromMe: bool
    id: str
    participant: Optional[str] = None
    # Evolution API v2: quando remoteJid é LID, o número real está em remoteJidAlt
    remoteJidAlt: Optional[str] = None
    addressingMode: Optional[str] = None  # 'lid' indica que remoteJid é um LID

class WebhookTextMessage(BaseModel):
    text: Optional[str] = None

class WebhookExtendedTextMessage(BaseModel):
    text: Optional[str] = None
    # v2 pode incluir campos adicionais
    contextInfo: Optional[Dict[str, Any]] = None
    matchedText: Optional[str] = None

class WebhookAudioMessage(BaseModel):
    url: Optional[str] = None
    mimetype: Optional[str] = "audio/ogg"
    fileSha256: Optional[Any] = None  # Aceita dict de bytes ou string
    fileLength: Optional[Any] = None  # v2 envia como {"low": N, "high": 0}
    seconds: Optional[int] = None
    ptt: Optional[bool] = False
    mediaKey: Optional[Any] = None  # Aceita dict de bytes ou string
    fileEncSha256: Optional[Any] = None  # Aceita dict de bytes ou string
    directPath: Optional[str] = None
    base64: Optional[str] = None
    # Campos adicionais v2
    waveform: Optional[Any] = None  # Aceita dict de bytes ou string
    mediaKeyTimestamp: Optional[Any] = None  # v2 envia como {"low": N, "high": 0}
    streamingSidecar: Optional[Any] = None  # v2 envia como dict de bytes
    model_config = ConfigDict(extra='allow')

    @field_validator('fileSha256', 'mediaKey', 'fileEncSha256', 'waveform', 'streamingSidecar', mode='before')
    @classmethod
    def convert_binary_fields(cls, v):
        """Converte campos binários de dict para base64 string"""
        return convert_byte_dict_to_base64(v)

    @field_validator('fileLength', 'mediaKeyTimestamp', mode='before')
    @classmethod
    def convert_length_fields(cls, v):
        """Converte campos de tamanho/timestamp de dict para int"""
        return convert_file_length(v)

class WebhookImageMessage(BaseModel):
    url: Optional[str] = None
    mimetype: Optional[str] = None
    caption: Optional[str] = None
    base64: Optional[str] = None
    # Campos adicionais v2
    width: Optional[int] = None
    height: Optional[int] = None
    jpegThumbnail: Optional[Any] = None  # Pode vir como dict de bytes
    fileSha256: Optional[Any] = None
    fileLength: Optional[Any] = None
    mediaKey: Optional[Any] = None
    fileEncSha256: Optional[Any] = None
    directPath: Optional[str] = None
    mediaKeyTimestamp: Optional[Any] = None
    model_config = ConfigDict(extra='allow')

    @field_validator('fileSha256', 'mediaKey', 'fileEncSha256', 'jpegThumbnail', mode='before')
    @classmethod
    def convert_binary_fields(cls, v):
        return convert_byte_dict_to_base64(v)

    @field_validator('fileLength', 'mediaKeyTimestamp', mode='before')
    @classmethod
    def convert_length_fields(cls, v):
        return convert_file_length(v)

class WebhookVideoMessage(BaseModel):
    url: Optional[str] = None
    mimetype: Optional[str] = None
    caption: Optional[str] = None
    seconds: Optional[int] = None
    base64: Optional[str] = None
    # Campos adicionais v2
    width: Optional[int] = None
    height: Optional[int] = None
    jpegThumbnail: Optional[Any] = None  # Pode vir como dict de bytes
    gifPlayback: Optional[bool] = None
    fileSha256: Optional[Any] = None
    fileLength: Optional[Any] = None
    mediaKey: Optional[Any] = None
    fileEncSha256: Optional[Any] = None
    directPath: Optional[str] = None
    mediaKeyTimestamp: Optional[Any] = None
    streamingSidecar: Optional[Any] = None
    model_config = ConfigDict(extra='allow')

    @field_validator('fileSha256', 'mediaKey', 'fileEncSha256', 'jpegThumbnail', 'streamingSidecar', mode='before')
    @classmethod
    def convert_binary_fields(cls, v):
        return convert_byte_dict_to_base64(v)

    @field_validator('fileLength', 'mediaKeyTimestamp', mode='before')
    @classmethod
    def convert_length_fields(cls, v):
        return convert_file_length(v)

class WebhookDocumentMessage(BaseModel):
    """Modelo para mensagens de documento - v2"""
    url: Optional[str] = None
    mimetype: Optional[str] = None
    title: Optional[str] = None
    fileName: Optional[str] = None
    fileLength: Optional[Any] = None
    base64: Optional[str] = None
    jpegThumbnail: Optional[Any] = None  # Pode vir como dict de bytes
    fileSha256: Optional[Any] = None
    mediaKey: Optional[Any] = None
    fileEncSha256: Optional[Any] = None
    directPath: Optional[str] = None
    mediaKeyTimestamp: Optional[Any] = None
    model_config = ConfigDict(extra='allow')

    @field_validator('fileSha256', 'mediaKey', 'fileEncSha256', 'jpegThumbnail', mode='before')
    @classmethod
    def convert_binary_fields(cls, v):
        return convert_byte_dict_to_base64(v)

    @field_validator('fileLength', 'mediaKeyTimestamp', mode='before')
    @classmethod
    def convert_length_fields(cls, v):
        return convert_file_length(v)

class WebhookStickerMessage(BaseModel):
    """Modelo para mensagens de sticker - v2"""
    url: Optional[str] = None
    mimetype: Optional[str] = None
    base64: Optional[str] = None
    isAnimated: Optional[bool] = None
    isAvatar: Optional[bool] = None
    fileSha256: Optional[Any] = None
    fileLength: Optional[Any] = None
    mediaKey: Optional[Any] = None
    fileEncSha256: Optional[Any] = None
    directPath: Optional[str] = None
    mediaKeyTimestamp: Optional[Any] = None
    width: Optional[int] = None
    height: Optional[int] = None
    model_config = ConfigDict(extra='allow')

    @field_validator('fileSha256', 'mediaKey', 'fileEncSha256', mode='before')
    @classmethod
    def convert_binary_fields(cls, v):
        return convert_byte_dict_to_base64(v)

    @field_validator('fileLength', 'mediaKeyTimestamp', mode='before')
    @classmethod
    def convert_length_fields(cls, v):
        return convert_file_length(v)

class WebhookLocationMessage(BaseModel):
    """Modelo para mensagens de localização - v2"""
    degreesLatitude: Optional[float] = None
    degreesLongitude: Optional[float] = None
    name: Optional[str] = None
    address: Optional[str] = None
    url: Optional[str] = None

class WebhookContactMessage(BaseModel):
    """Modelo para mensagens de contato - v2"""
    displayName: Optional[str] = None
    vcard: Optional[str] = None

class WebhookReactionMessage(BaseModel):
    """Modelo para mensagens de reação - v2"""
    key: Optional[Dict[str, Any]] = None
    text: Optional[str] = None


class WebhookMessageContextInfo(BaseModel):
    """Modelo para messageContextInfo - v2"""
    deviceListMetadata: Optional[Dict[str, Any]] = None
    deviceListMetadataVersion: Optional[int] = None
    messageSecret: Optional[Any] = None  # Pode vir como dict de bytes
    model_config = ConfigDict(extra='allow')

    @field_validator('messageSecret', mode='before')
    @classmethod
    def convert_message_secret(cls, v):
        return convert_byte_dict_to_base64(v)


class WebhookMessageContent(BaseModel):
    conversation: Optional[str] = None
    textMessage: Optional[WebhookTextMessage] = None
    extendedTextMessage: Optional[WebhookExtendedTextMessage] = None
    audioMessage: Optional[WebhookAudioMessage] = None
    imageMessage: Optional[WebhookImageMessage] = None
    videoMessage: Optional[WebhookVideoMessage] = None
    documentMessage: Optional[WebhookDocumentMessage] = None
    stickerMessage: Optional[WebhookStickerMessage] = None
    locationMessage: Optional[WebhookLocationMessage] = None
    contactMessage: Optional[WebhookContactMessage] = None
    reactionMessage: Optional[WebhookReactionMessage] = None
    base64: Optional[str] = None
    # v2 campos adicionais
    buttonsResponseMessage: Optional[Dict[str, Any]] = None
    listResponseMessage: Optional[Dict[str, Any]] = None
    templateButtonReplyMessage: Optional[Dict[str, Any]] = None
    messageContextInfo: Optional[WebhookMessageContextInfo] = None
    model_config = ConfigDict(extra='allow')

class WebhookPayload(BaseModel):
    """
    Payload principal do webhook - compatível com v1 e v2.
    v1 usa 'instance', v2 usa 'instanceName'
    """
    event: str
    # Suporte para ambos: instance (v1) e instanceName (v2)
    instance: Optional[str] = None
    instanceName: Optional[str] = None
    data: Optional[Any] = None
    sender: Optional[str] = None
    # Campos adicionais v2
    serverUrl: Optional[str] = None
    dateTime: Optional[str] = None
    apiKey: Optional[str] = None
    origin: Optional[str] = None
    model_config = ConfigDict(extra='allow')

    @model_validator(mode='after')
    def normalize_instance_name(self):
        """Garante que instance tenha um valor, preferindo instanceName se disponível"""
        if self.instanceName and not self.instance:
            self.instance = self.instanceName
        elif self.instance and not self.instanceName:
            self.instanceName = self.instance
        return self

    def get_instance_name(self) -> str:
        """Retorna o nome da instância, priorizando instanceName (v2) sobre instance (v1)"""
        return self.instanceName or self.instance or "unknown"

class ConnectionUpdateData(BaseModel):
    state: str
    instance: Optional[str] = None
    # Campos adicionais v2
    statusReason: Optional[int] = None

class ConnectionUpdatePayload(WebhookPayload):
    """Payload de atualização de conexão - compatível com eventos v1 e v2"""
    event: str  # Removido Literal para suportar 'connection.update' e 'CONNECTION_UPDATE'
    data: ConnectionUpdateData

    @field_validator('event')
    @classmethod
    def validate_event(cls, v):
        """Aceita tanto 'connection.update' (v1) quanto 'CONNECTION_UPDATE' (v2)"""
        valid_events = ['connection.update', 'CONNECTION_UPDATE']
        if v.lower().replace('_', '.') == 'connection.update' or v.upper() == 'CONNECTION_UPDATE':
            return v
        raise ValueError(f"Event must be one of {valid_events}, got {v}")

class WebhookMessageData(BaseModel):
    """
    Dados da mensagem do webhook - compatível com v1 e v2.
    v1 usa 'owner', v2 usa 'instanceId'
    """
    key: WebhookMessageKey
    message: Optional[WebhookMessageContent] = None
    messageTimestamp: Optional[int] = None
    # Suporte para ambos: owner (v1) e instanceId (v2)
    owner: Optional[str] = None
    instanceId: Optional[str] = None
    remoteJid: Optional[str] = None
    participant: Optional[str] = None
    pushName: Optional[str] = None
    broadcast: Optional[bool] = None
    fromMe: Optional[bool] = None
    status: Optional[Union[int, str]] = None  # v2 envia strings como "DELIVERY_ACK", "READ", "PLAYED"
    mediaData: Optional[Dict[str, Any]] = None
    # Campos adicionais v2
    messageType: Optional[str] = None
    source: Optional[str] = None
    contextInfo: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra='allow')

    @model_validator(mode='after')
    def normalize_owner_instance(self):
        """Garante compatibilidade entre owner (v1) e instanceId (v2)"""
        if self.instanceId and not self.owner:
            self.owner = self.instanceId
        elif self.owner and not self.instanceId:
            self.instanceId = self.owner
        return self

    def get_owner(self) -> Optional[str]:
        """Retorna o owner/instanceId, priorizando instanceId (v2) sobre owner (v1)"""
        return self.instanceId or self.owner


# --- Utilitários para normalização de eventos ---

def normalize_event_name(event: str) -> str:
    """
    Normaliza o nome do evento para formato consistente.
    Converte UPPERCASE_SNAKE_CASE (v2) para lowercase.dot.case (v1 style interno)

    Exemplos:
        'MESSAGES_UPSERT' -> 'messages.upsert'
        'CONNECTION_UPDATE' -> 'connection.update'
        'messages.upsert' -> 'messages.upsert' (já no formato correto)
    """
    if '.' in event:
        return event.lower()
    return event.lower().replace('_', '.')


# Mapeamento de eventos v2 -> v1 para compatibilidade interna
EVENT_MAP_V2_TO_V1 = {
    'MESSAGES_UPSERT': 'messages.upsert',
    'MESSAGES_UPDATE': 'messages.update',
    'MESSAGES_DELETE': 'messages.delete',
    'MESSAGES_SET': 'messages.set',
    'MESSAGES_EDITED': 'messages.edited',
    'CONNECTION_UPDATE': 'connection.update',
    'QRCODE_UPDATED': 'qrcode.updated',
    'APPLICATION_STARTUP': 'application.startup',
    'CONTACTS_UPSERT': 'contacts.upsert',
    'CONTACTS_UPDATE': 'contacts.update',
    'CONTACTS_SET': 'contacts.set',
    'CHATS_UPSERT': 'chats.upsert',
    'CHATS_UPDATE': 'chats.update',
    'CHATS_DELETE': 'chats.delete',
    'CHATS_SET': 'chats.set',
    'PRESENCE_UPDATE': 'presence.update',
    'GROUPS_UPSERT': 'groups.upsert',
    'GROUP_UPDATE': 'group.update',
    'GROUP_PARTICIPANTS_UPDATE': 'group.participants.update',
    'SEND_MESSAGE': 'send.message',
    'SEND_MESSAGE_UPDATE': 'send.message.update',
    'LABELS_EDIT': 'labels.edit',
    'LABELS_ASSOCIATION': 'labels.association',
    'CALL': 'call',
    'TYPEBOT_START': 'typebot.start',
    'TYPEBOT_CHANGE_STATUS': 'typebot.change.status',
    'REMOVE_INSTANCE': 'remove.instance',
    'LOGOUT_INSTANCE': 'logout.instance',
    'INSTANCE_CREATE': 'instance.create',
    'INSTANCE_DELETE': 'instance.delete',
    'STATUS_INSTANCE': 'status.instance',
}
