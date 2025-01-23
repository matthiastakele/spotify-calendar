from typing import List, Dict, Any
from flask import Flask, request, url_for, session, redirect, render_template, make_response
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import time
import datetime
import random
import copy 
# Load environment variables
load_dotenv()

SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY")
app.config['SESSION_COOKIE_NAME'] = 'Spotify Top Artist Trivia'
TOKEN_INFO = "token_info"

def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope="user-top-read user-library-read",
        cache_path=None,  # Ensure no caching
        show_dialog=True
    )

def get_token():
    token_info = session.get(TOKEN_INFO)
    if not token_info:
        raise Exception("No token info found in session.")

    now = int(time.time())
    is_expired = token_info['expires_at'] - now < 60

    if is_expired:
        sp_oauth = create_spotify_oauth()
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        session[TOKEN_INFO] = token_info

    return token_info


@app.route('/')
def login():
    session.clear()  # Clear previous session data
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/logout')
def logout():
    # Clear the session on your application
    session.clear()

    cache_path = os.path.join(os.getcwd(), ".cache")
    if os.path.exists(cache_path):
        os.remove(cache_path)
        print("DEBUG: .cache file removed")

    return redirect(url_for('home'))


@app.context_processor
def inject_logged_in():
    token_info = session.get(TOKEN_INFO, None)
    if token_info:
        now = int(time.time())
        return {"logged_in": token_info.get('expires_at', 0) > now}
    return {"logged_in": False}

@app.route('/redirect')
def redirectPage():
    sp_oauth = create_spotify_oauth()
    code = request.args.get('code')

    if not code:
        return "Authorization code not received.", 400

    try:
        # Get new token info
        token_info = sp_oauth.get_access_token(code)
        session[TOKEN_INFO] = token_info

        # Create Spotify client
        sp = spotipy.Spotify(auth=token_info['access_token'])
        # Get current user's profile
        user_profile = sp.current_user()
        print(user_profile['display_name'])
        session['USER_ID'] = user_profile['id']

        # Fetch and store top artists for the current user
        top_artists = sp.current_user_top_artists(limit=12, time_range='medium_term')['items']
        session['TOP_ARTISTS'] = top_artists

        return redirect(url_for('pickTopArtist'))

    except Exception as e:
        print(f"Error during redirect: {e}")
        return redirect(url_for('login'))


@app.route('/pickTopArtist')
def pickTopArtist():
    try:
        user_id = session.get('USER_ID')
        top_artists = session.get('TOP_ARTISTS')

        if not user_id or not top_artists:
            return redirect(url_for('login'))

        return render_template('pick_top_artist.html', top_artists=top_artists)
    except Exception as e:
        print(f"Error in pickTopArtist: {e}")
        return redirect(url_for('login'))


@app.route('/selectArtist', methods=['POST'])
def selectArtist():
    selected_artist_id = request.form['artist_id']
    if not selected_artist_id:
        return "No artist selected.", 400
    session['selected_artist_id'] = selected_artist_id
    return redirect(url_for('trivia'))

class TriviaQuestionGenerator:
    def __init__(self, spotify_client: spotipy.Spotify, artist_id: str):
        self.sp = spotify_client
        self.artist_id = artist_id
        self.artist_info = self.sp.artist(artist_id)
        self.top_tracks = self.sp.artist_top_tracks(artist_id, country='US')['tracks']
        self.albums = self.sp.artist_albums(artist_id, album_type='album')['items']
        self.albums_with_tracks = self._prepare_albums_with_tracks()

    def _prepare_albums_with_tracks(self) -> Dict:
        """Prepare nested album and track data."""
        albums_with_tracks = {}
        for album in self.albums:
            tracks = self.sp.album_tracks(album['id'])['items']
            albums_with_tracks[album['name']] = {
                "release_date": album['release_date'],
                "tracks": [{"name": track['name'], "duration_ms": track['duration_ms']} 
                          for track in tracks]
            }
        return albums_with_tracks

    def _generate_diff_album_tracks(self, correct_track: str, correct_album: str, num_of_tracks: int = 3) -> List[str]:
        """Generate tracks from different albums for wrong options."""
        tracks = []
        shuffled_albums = random.sample(list(self.albums_with_tracks.keys()), len(self.albums_with_tracks))
        for album in shuffled_albums:
            if album == correct_album or album.startswith(correct_album) or correct_album.startswith(album):
                shuffled_albums.remove(album)
    
        if len(shuffled_albums) >= 1:
            selected_tracks = set()
            while len(tracks) != num_of_tracks:
                diff_album = random.choice(shuffled_albums)
                diff_track = random.choice(self.albums_with_tracks[diff_album]['tracks'])['name']

                if diff_track not in selected_tracks and diff_track != correct_track:
                    selected_tracks.add(diff_track)
                    tracks.append(diff_track)

        return tracks

    def generate_followers_question(self) -> Dict:
        """Generate question about artist's follower count."""
        followers = self.artist_info['followers']['total']
        return {
            "question": f"How many Spotify followers does {self.artist_info['name']} have?",
            "options": [
                "{:,}".format(int(followers * multiplier))
                for multiplier in [0.5, 0.7, 1.0, 1.3]
            ],
            "answer": followers
        }
    
    def generate_genre_question(self) -> Dict:
        """Generate question about artist's genre."""
        artist_genres = self.artist_info.get('genres')
        if artist_genres:
            artist_genre = artist_genres[0]
            all_genres = {'rock', 'pop', 'r&b', 'jazz', 'hip hop'}
            other_genres = [genre for genre in random.sample(list(all_genres - {artist_genre}), 3)]
            return {
                "question": f"What genre is {self.artist_info['name']}'s music?",
                "options": [artist_genre] + other_genres,
                "answer": artist_genre
            }
        else:
            return {}

    def generate_recent_album_question(self) -> Dict:
        """Generate question about most recent album."""
        most_recent = max(self.albums, key=lambda x: x['release_date'])
        other_albums = random.sample([a for a in self.albums if a != most_recent], min(3, len(self.albums)-1))
        if other_albums:
            return {
                "question": f"What is the most recently released album by {self.artist_info['name']}?",
                "options": [most_recent['name']] + [a['name'] for a in other_albums],
                "answer": most_recent['name']
            }
        return {}

    def generate_track_album_questions(self) -> List[Dict]:
        """Generate questions about which tracks belong to which albums."""
        questions = []
        for album_name, details in self.albums_with_tracks.items():
            if details['tracks']:
                correct_track = random.choice(details['tracks'])['name']
                diff_tracks = self._generate_diff_album_tracks(correct_track, album_name)
                if not diff_tracks:
                    return {}
                questions.append({
                    "question": f"Which track is on the album '{album_name}'?",
                    "options": [correct_track] + diff_tracks,
                    "answer": correct_track
                })

        return questions

    def generate_album_year_questions(self) -> List[Dict]:
        """Generate questions about various album release years."""
        questions = []
        for album in self.albums:
            release_year = int(album['release_date'][:4])
            current_year = datetime.datetime.now().year

            diff_years = [
                release_year + i
                for i in range(-4, 4) 
                if i != 0 and (release_year + i) <= current_year
            ]
            
            options = random.sample(diff_years, 3) + [release_year]
            questions.append({
                "question": f"In what year was the album '{album['name']}' released?",
                "options": options,
                "answer": release_year
            })

        return questions
    
    def generate_album_track_count_questions(self) -> List[Dict]:
        """Generate questions about the track abount of various albums"""
        questions = []
        for album_name, album_data in self.albums_with_tracks.items():
            track_count = len(album_data['tracks'])
            diff_track_counts = [
                max(1, track_count + i)
                for i in range(-4, 5)
                if i != 0 and (track_count + i) > 0
            ]

            options = random.sample(diff_track_counts, 3) + [track_count]
            questions.append({
                "question": f"How many tracks are on '{album_name}'?",
                "options": options,
                "answer": track_count
            })

        return questions

    def get_questions(self, num_questions: int = 10) -> List[Dict]:
        """Generate a set of trivia questions."""
        all_questions = []
        
        # Add one of each question type
        question_generators = [
            self.generate_followers_question,
            self.generate_recent_album_question,
            self.generate_genre_question
        ]

        multiple_question_generators = [
            self.generate_track_album_questions,
            self.generate_album_year_questions,
            self.generate_album_track_count_questions
        ]

        for generator in question_generators:
            all_questions.append(generator())
        
        other_questions = [generator() for generator in multiple_question_generators]
        all_other_questions = [q for questions in other_questions for q in questions]

        if len(all_questions) + len(all_other_questions) < 10:
            all_questions.extend(all_other_questions)
            random.shuffle(all_questions)
            return all_questions

        i = 0
        while len(all_questions) < 10:
            try:
                all_questions.extend([questions[i] for questions in other_questions])
                i += 1
            except:
                break
        
        # Shuffle and limit to desired number
        random.shuffle(all_questions)
        return all_questions[:num_questions]

@app.route('/trivia')
def trivia():
    selected_artist_id = session.get('selected_artist_id')
    if not selected_artist_id:
        return redirect(url_for('pickTopArtist'))

    try:
        token_info = get_token()
        sp = spotipy.Spotify(auth=token_info['access_token'])
        
        # Generate questions using the new class
        generator = TriviaQuestionGenerator(sp, selected_artist_id)
        questions = generator.get_questions()
        questions = [q for q in questions if q]
        for q in questions:
            random.shuffle(q['options'])
        
        # Store albums_with_tracks in session for potential future use
        session['albums_with_tracks'] = generator.albums_with_tracks
        session['questions'] = questions
        
        return render_template('trivia.html', 
                             artist=generator.artist_info, 
                             questions=questions)
    except Exception as e:
        print(f"Error: {e}")
        return "An error occurred while fetching artist data.", 500

@app.route('/submitTrivia', methods=['POST'])
def submitTrivia():
    # Retrieve questions and correct answers from session or context
    questions = session.get('questions', [])
    total_questions = len(questions)

    if not questions:
        return redirect(url_for('trivia'))  # Redirect back if no questions found

    # Process form data
    correct_answers = 0
    recap = []

    for i, question in enumerate(questions, start=1):
        user_answer = str(request.form.get(f"question_{i}")).replace(',','')
        question_answer = str(question['answer'])
        is_correct = user_answer == question_answer

        if is_correct:
            correct_answers += 1

        # Add to recap for detailed results
        recap.append({
            "question": question['question'],
            "user_answer": user_answer,
            "correct_answer": question['answer'],
            "is_correct": is_correct
        })

    # Calculate percentage of correct and incorrect answers
    correct_percentage = (correct_answers / total_questions) * 100
    incorrect_percentage = 100 - correct_percentage

    # Render results page
    return render_template(
        'results.html',
        correct_percentage=str(round(correct_percentage,2)),
        incorrect_percentage=str(round(incorrect_percentage,2)),
        total_questions=total_questions,
        correct_answers=correct_answers,
        incorrect_answers=total_questions - correct_answers,
        recap=recap  # Pass recap to template
    )


@app.route('/home')
def home():
    return render_template('home.html')

if __name__ == '__main__':
    app.run()
