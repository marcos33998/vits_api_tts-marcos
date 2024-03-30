import random
import re
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder
import string as stringlib
from pathlib import Path

import gradio as gr

from modules import chat, shared, ui_chat
from modules.logging_colors import logger
from modules.utils import gradio

params = {
    'activate': True,
    'base_url': None,
    'selected_voice': 'None',
    'autoplay': False,
    'show_text': True,
}

voices = None
wav_idx = 0


def update_base_url(key):
    params['base_url'] = key


def refresh_voices():
    global params
    voice_names = ['128.香菱']
    if params['base_url'] is not None:
        url = f"{params['base_url']}/voice/speakers"
        res = requests.post(url=url)
        json = res.json()
        # TODO: change model HUBERT-VITS and W2V2-VITS
        your_voices = json['VITS']
        voice_names = [f"{voice['id']}.{voice['name']}" for voice in your_voices]
    return voice_names


def refresh_voices_dd():
    all_voices = refresh_voices()
    return gr.Dropdown.update(value=all_voices[0], choices=all_voices)


def remove_tts_from_history(history):
    for i, entry in enumerate(history['internal']):
        history['visible'][i] = [history['visible'][i][0], entry[1]]

    return history


def toggle_text_in_history(history):
    for i, entry in enumerate(history['visible']):
        visible_reply = entry[1]
        if visible_reply.startswith('<audio'):
            if params['show_text']:
                reply = history['internal'][i][1]
                history['visible'][i] = [history['visible'][i][0], f"{visible_reply.split('</audio>')[0]}</audio>\n\n{reply}"]
            else:
                history['visible'][i] = [history['visible'][i][0], f"{visible_reply.split('</audio>')[0]}</audio>"]

    return history


def remove_surrounded_chars(string):
    # this expression matches to 'as few symbols as possible (0 upwards) between any asterisks' OR
    # 'as few symbols as possible (0 upwards) between an asterisk and the end of the string'
    return re.sub('\*[^\*]*?(\*|$)', '', string)


def state_modifier(state):
    if not params['activate']:
        return state

    state['stream'] = False
    return state


def input_modifier(string):
    if not params['activate']:
        return string

    shared.processing_message = "*Is recording a voice message...*"
    return string


def history_modifier(history):
    # Remove autoplay from the last reply
    if len(history['internal']) > 0:
        history['visible'][-1] = [
            history['visible'][-1][0],
            history['visible'][-1][1].replace('controls autoplay>', 'controls>')
        ]

    return history


def output_modifier(string):
    global params, wav_idx

    if not params['activate']:
        return string

    original_string = string
    string = remove_surrounded_chars(string)
    string = string.replace('"', '')
    string = string.replace('“', '')
    string = string.replace('\n', ' ')
    string = string.strip()
    if string == '':
        string = 'empty reply, try regenerating'

    output_file = Path(f'extensions/vits_api_tts/outputs/{wav_idx:06d}.mp3'.format(wav_idx))
    id = params['selected_voice'].split('.')[0]
    print(f'Outputting audio to {str(output_file)}')
    fields = {
        "text": string,
        "id": str(id),
        "format": "wav",
        "lang": "auto",
        "length": str(1),
        "noise": str(0.667),
        "noisew": str(0.8),
        "max": str(50),
        "streaming": str(True)
    }
    boundary = '----VoiceConversionFormBoundary' + ''.join(random.sample(stringlib.ascii_letters + stringlib.digits, 16))

    m = MultipartEncoder(fields=fields, boundary=boundary)
    headers = {"Content-Type": m.content_type}
    url = f"{params['base_url']}/voice"

    res = requests.post(url=url, data=m, headers=headers)
    with open(output_file, "wb") as f:
        f.write(res.content)

    autoplay = 'autoplay' if params['autoplay'] else ''
    string = f'<audio src="file/{output_file.as_posix()}" controls {autoplay}></audio>'
    wav_idx += 1

    if params['show_text']:
        string += f'\n\n{original_string}'

    shared.processing_message = "*Is typing...*"
    return string


def ui():
    global voices
    if not voices:
        voices = refresh_voices()
        selected = params['selected_voice']
        if selected == 'None':
            params['selected_voice'] = voices[0]
        elif selected not in voices:
            logger.error(f'Selected voice {selected} not available, switching to {voices[0]}')
            params['selected_voice'] = voices[0]

    # Gradio elements
    with gr.Row():
        activate = gr.Checkbox(value=params['activate'], label='Activate TTS')
        autoplay = gr.Checkbox(value=params['autoplay'], label='Play TTS automatically')
        show_text = gr.Checkbox(value=params['show_text'], label='Show message text under audio player')

    with gr.Row():
        voice = gr.Dropdown(value=params['selected_voice'], choices=voices, label='TTS Voice')
        refresh = gr.Button(value='Refresh')

    with gr.Row():
        if params['base_url']:
            base_url = gr.Textbox(value=params['base_url'], label='Base URL')
            update_base_url(params['base_url'])
        else:
            base_url = gr.Textbox(placeholder="Enter your base URL.", label='Base URL')

    with gr.Row():
        convert = gr.Button('Permanently replace audios with the message texts')
        convert_cancel = gr.Button('Cancel', visible=False)
        convert_confirm = gr.Button('Confirm (cannot be undone)', variant="stop", visible=False)

    # Convert history with confirmation
    convert_arr = [convert_confirm, convert, convert_cancel]
    convert.click(lambda: [gr.update(visible=True), gr.update(visible=False), gr.update(visible=True)], None, convert_arr)
    convert_confirm.click(
        lambda: [gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)], None, convert_arr).then(
        remove_tts_from_history, gradio('history'), gradio('history')).then(
        chat.save_persistent_history, gradio('history', 'character_menu', 'mode'), None).then(
        chat.redraw_html, gradio(ui_chat.reload_arr), gradio('display'))

    convert_cancel.click(lambda: [gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)], None, convert_arr)

    # Toggle message text in history
    show_text.change(
        lambda x: params.update({"show_text": x}), show_text, None).then(
        toggle_text_in_history, gradio('history'), gradio('history')).then(
        chat.save_persistent_history, gradio('history', 'character_menu', 'mode'), None).then(
        chat.redraw_html, gradio(ui_chat.reload_arr), gradio('display'))

    # Event functions to update the parameters in the backend
    activate.change(lambda x: params.update({'activate': x}), activate, None)
    voice.change(lambda x: params.update({'selected_voice': x}), voice, None)
    base_url.change(update_base_url, base_url, None)
    refresh.click(refresh_voices_dd, [], voice)
    # Event functions to update the parameters in the backend
    autoplay.change(lambda x: params.update({"autoplay": x}), autoplay, None)
