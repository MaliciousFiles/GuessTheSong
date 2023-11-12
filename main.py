import discord_typings
import interactions
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from pytube import YouTube, Search
from moviepy.editor import *
from interactions import *

import os
import re
import shutil
import random
import uuid
import dotenv
import tempfile
import atexit
from appdirs import *

# Dirs
appname = "GuessTheSong"
appauthor = "MaliciousFiles"
roaming_dir = user_data_dir(appname, appauthor, roaming=True)
cache_dir = user_cache_dir(appname, appauthor)
temp_dir = tempfile.gettempdir()

if not os.path.exists(roaming_dir):
    os.makedirs(roaming_dir)

env_file = os.path.join(roaming_dir, ".env")
if not os.path.exists(env_file):
    with open(env_file, "x") as f:
        pass

loading_file = os.path.join(cache_dir, "loading")
if not os.path.exists(loading_file):
    with open(loading_file, "xb") as f:
        pass

# Global Variables
PLAYLIST_URL_REGEX = "(https://)?open.spotify.com/playlist/[a-zA-Z0-9]{22}(\\?.*)?"

ERROR_COLOR: Color = Color("#e02626")

GUESS_COLORS: list[Color] = [Color("#8bf04d"), Color("#b2f04d"), Color("#cdf04d"), Color("#e8f04d"), Color("#f0c54d"),
                             Color("#f06e4d")]
WIN_COLOR: Color = Color("#6af041")
LOSE_COLOR: Color = Color("#f04741")

DURATIONS = [1, 3, 7, 10, 15, 25]

spotify = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials(
    client_id=dotenv.get_key(env_file, "SPOTIFY_CLIENT_ID"),
    client_secret=dotenv.get_key(env_file, "SPOTIFY_CLIENT_SECRET")
))
bot = Client()

track_id_to_guess: dict[
    str, list[int]] = {}  # this is important, so we can know whether it's safe to delete the cached MP3 file later on

guess_to_track_id: dict[int, str] = {-1: ""}
guess_to_guess_history: dict[int, list[bool]] = {-1: []}  # the bool is whether it was skipped
guess_to_album_cover: dict[int, str] = {-1: ""}
guess_to_hints: dict[int, list[EmbedField]] = {-1: []}
guess_to_album_title: dict[int, str] = {-1: ""}
guess_to_track_title: dict[int, str] = {-1: ""}
guess_to_guess_idx: dict[int, int] = {-1: 0}
guess_to_playlist_url: dict[int, str] = {-1: ""}


def get_embed(guess_id: int, won: bool = None):
    history = guess_to_guess_history[guess_id]
    guess_idx = guess_to_guess_idx[guess_id]

    fields = guess_to_hints[guess_id][:(guess_idx if won is None else len(DURATIONS))]

    if won is not None:
        for f in fields:
            if f.value == "*[Single]*":
                f.value = guess_to_album_title[guess_id]

    return Embed(
        title="Guess the Song!" if won is None else guess_to_track_title[guess_id],
        description="  ".join([":black_large_square:" if s else ":red_square:" for s in history] +
                              [":green_square:" if won and i == 0 else ":white_medium_small_square:"
                               for i in range(len(DURATIONS) - len(history))]),
        fields=fields,
        thumbnail=guess_to_album_cover[guess_id] if any(map(lambda f: f.name == "Album", fields)) else None,
        color=GUESS_COLORS[guess_idx] if won is None else WIN_COLOR if won else LOSE_COLOR
    )


# TODO: better algorithm for checking if you're correct
# TODO: if won, keep clip that they guessed it on
# TODO: some way to challenge?
# TODO: param for difficulty
# TODO: param for starting at the beginning/90 secs from end/random
# TODO: maybe safeguard against same song?
# TODO: remove song after time (so if they dismiss it)
@slash_command(
    name="guess",
    description="Get a new song to guess!",
    options=[
        SlashCommandOption(
            name="playlist",
            description="Spotify playlist from which to take the songs",
            type=OptionType.STRING
        )
    ]
)
async def guess_command(ctx: SlashContext, playlist: str):
    if not re.match(PLAYLIST_URL_REGEX, playlist):
        await ctx.respond(embed=Embed(
            title="Invalid Playlist",
            description="Input playlist is not a valid Spotify url.",
            color=ERROR_COLOR
        ), ephemeral=True)
        return

    components = [
        Button(
            style=ButtonStyle.GREEN,
            label="Guess!",
            custom_id="guess",
            disabled=True
        ),
        Button(
            style=ButtonStyle.GRAY,
            label="Skip",
            custom_id="skip",
            disabled=True
        )
    ]
    msg = await ctx.respond(embed=get_embed(-1), file=loading_file, components=components, ephemeral=True)

    for c in components:
        c.disabled = False

    try:
        num_tracks = spotify.playlist(playlist, fields="tracks.total")['tracks']['total']
    except spotipy.SpotifyException:
        await ctx.respond(
            embed=Embed(
                title="Playlist Not Found",
                description="The playlist given is either invalid or private",
                color=ERROR_COLOR
            )
        )
        return

    track = spotify.playlist_items(playlist,
                                   fields="items(track(album(name,release_date,id,total_tracks,images.url),artists(name,id),name,duration_ms))",
                                   offset=random.randint(0, num_tracks - 1),
                                   limit=1)["items"][0]['track']

    artists = ', '.join(map(lambda a: a['name'], track['artists']))

    track_id = re.sub('[\\\/:*?"<>|]', "", (track['name'] + " - " + track['album']['name'] + " by " + artists))

    query = f"{artists} - {track['name']} ({track['album']['name']})"

    try:
        # only check the first 10 (past that probably isn't accurate),
        # then limit them to within 5 seconds of what spotify says the
        # duration should be, then take the closest
        vid = next(filter(lambda res: abs(int(next(filter(lambda f: f['itag'] == 140,
                                                          res.vid_info['streamingData']['adaptiveFormats']))['approxDurationMs'])
                                          - int(track['duration_ms'])) <= 20000,
                          filter(lambda res: 'streamingData' in res.vid_info, Search(query).results[:10])))
    except StopIteration:
        await ctx.respond(embed=Embed(
            color=ERROR_COLOR,
            title="Failed to Find Song",
            description=f"Failed to find YouTube video for `{query}`. Please report to **maliciousfiles** for debugging, and run the command again."
        ), ephemeral=True)
        return

    vid.streams.get_by_itag(140).download(output_path=cache_dir, filename=f"{track_id}.mp3")

    file = get_audio_clip(track_id, 0)

    await ctx.client.http.edit_interaction_message(
        payload=process_message_payload(components=components),
        application_id=ctx.client.app.id,
        token=ctx.token,
        message_id=to_snowflake(msg.id),
        files=file
    )

    shutil.rmtree(os.path.dirname(file))

    track_id_to_guess.setdefault(track_id, [])
    track_id_to_guess[track_id].append(msg.id)

    seconds = int(track['duration_ms']) // 1000
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    genres = spotify.album(track['album']['id'])['genres']
    if len(genres) == 0:
        genres = spotify.artist(track['artists'][0]['id'])['genres']
    if len(genres) == 0:
        genres = ["Unknown"]

    guess_to_track_id[msg.id] = track_id
    guess_to_hints[msg.id] = [
        EmbedField("Duration", (f"{hours}:{minutes:02d}" if hours > 0 else f"{minutes}") + f":{seconds:02d}", True),
        EmbedField("Release Year", track['album']['release_date'].split("-")[0], True),
        EmbedField("Genre", ", ".join([g.title() for g in genres]), True),
        EmbedField("Artist", artists, True),
        EmbedField("Album", "*[Single]*" if track['album']['total_tracks'] == 1 else track['album']['name'], True)
    ]
    guess_to_album_title[msg.id] = track['album']['name']
    guess_to_album_cover[msg.id] = track['album']['images'][0]['url']
    guess_to_guess_history[msg.id] = []
    guess_to_track_title[msg.id] = track['name']
    guess_to_guess_idx[msg.id] = 0
    guess_to_playlist_url[msg.id] = playlist


@component_callback("guess")
async def guess_callback(ctx: ComponentContext):
    await ctx.send_modal(Modal(
        ShortText(
            label="Song Title",
            custom_id="title"
        ),
        title="Guess the Song",
        custom_id="guess_modal"
    ))


async def finish(ctx: ComponentContext | ModalContext, won: bool):
    track_id = guess_to_track_id[ctx.message_id]

    embed = get_embed(ctx.message_id, won)
    file = os.path.join(cache_dir, f"{track_id}.mp3")

    components = [
        Button(
            style=ButtonStyle.GREEN,
            label="Play Again",
            custom_id=f"play_again~{guess_to_playlist_url[ctx.message_id]}"
        ),
        Button(
            style=ButtonStyle.BLUE,
            label="Share",
            custom_id="share",
            disabled=True
        )
    ]

    # I don't know why I have to do this manually, but here we are. Same as what happens behind the scenes in `ctx.edit`
    await ctx.defer(edit_origin=True)
    await ctx.client.http.edit_interaction_message(
        payload=process_message_payload(components=components, embeds=embed),
        application_id=ctx.client.app.id,
        token=ctx.token,
        message_id=to_snowflake(ctx.message_id),
        files=loading_file
    )

    components[1].disabled = False
    await ctx.edit(ctx.message_id, components=components, file=file)

    track_id_using = track_id_to_guess[track_id]
    track_id_using.remove(ctx.message_id)
    if len(track_id_using) == 0:
        del track_id_to_guess[track_id]
        os.remove(file)

    del guess_to_track_id[ctx.message_id]
    del guess_to_track_title[ctx.message_id]
    del guess_to_hints[ctx.message_id]
    del guess_to_guess_history[ctx.message_id]
    del guess_to_guess_idx[ctx.message_id]


async def next_guess(ctx: ComponentContext | ModalContext, skipped: bool):
    guess_to_guess_idx[ctx.message_id] += 1
    guess = guess_to_guess_idx[ctx.message_id]

    guess_to_guess_history[ctx.message_id].append(skipped)

    if guess >= len(DURATIONS):
        await finish(ctx, False)
        return

    components = ctx.message.components

    for c in components[0].components:
        c.disabled = True

    # I don't know why I have to do this manually, but here we are. Same as what happens behind the scenes in `ctx.edit`
    await ctx.defer(edit_origin=True)
    await ctx.client.http.edit_interaction_message(
        payload=process_message_payload(components=components),
        application_id=ctx.client.app.id,
        token=ctx.token,
        message_id=to_snowflake(ctx.message_id),
        files=loading_file
    )

    for c in components[0].components:
        c.disabled = False

    await ctx.edit(ctx.message_id, embed=get_embed(ctx.message_id), components=components,
                   file=get_audio_clip(guess_to_track_id[ctx.message_id], guess))


@component_callback("skip")
async def skip_callback(ctx: ComponentContext):
    await next_guess(ctx, True)


@component_callback("share")
async def share_callback(ctx: ComponentContext):
    attachment = ctx.message.attachments[0]

    embed = ctx.message.embeds[0]
    embed.set_author(ctx.author.display_name, icon_url=ctx.author.display_avatar.url)

    file = os.path.join(tempfile.gettempdir(), attachment.filename)
    download_webfile(attachment.url, file)

    components = ctx.message.components[0].components
    components.remove(next(filter(lambda c: c.custom_id == ctx.custom_id, components)))

    await ctx.edit_origin(components=components)

    msg = await ctx.channel.send(file=loading_file, embed=embed)
    await msg.edit(file=file)

    os.remove(file)


@component_callback(re.compile(f"play_again~{PLAYLIST_URL_REGEX}"))
async def play_again_callback(ctx: ComponentContext):
    message = ctx.message

    ctx.kwargs['playlist'] = ctx.custom_id.split('~')[1]
    await guess_command(ctx)

    components = message.components[0].components
    components.remove(next(filter(lambda c: c.custom_id == ctx.custom_id, components)))

    ctx.editing_origin = True
    await ctx.edit(message.id, components=components)


@modal_callback("guess_modal")
async def guess_modal_callback(ctx: ModalContext, title: str):
    # TODO: better algorithm
    for word in title.lower().split(' '):
        if word not in guess_to_track_title[ctx.message_id].lower():
            await next_guess(ctx, False)
            return

    await finish(ctx, True)


def get_audio_clip(track_id: str, guess_idx: int):
    audio_clip = AudioFileClip(os.path.join(cache_dir, f"{track_id}.mp3"))
    audio_clip = audio_clip.subclip(audio_clip.duration - 90, audio_clip.duration - 90 + DURATIONS[guess_idx])

    path = os.path.join(temp_dir, f"GuessTheSong_{uuid.uuid4()}", "mystery.mp3")
    os.mkdir(os.path.dirname(path))

    audio_clip.write_audiofile(path)
    audio_clip.close()

    return path


def clear_cache():
    for file in os.listdir(cache_dir):
        os.remove(file)


atexit.register(clear_cache)
bot.start(dotenv.get_key(env_file, "BOT_TOKEN"))
