from django.shortcuts import render, get_object_or_404, redirect
from .models import Playlist, Movie, DownloadLog, InstallTracker, Category
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Count, Q
from itertools import chain
import json
import re
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator, EmptyPage

# -------------------------------
# Helper function: Robust Season and Episode number extraction
# -------------------------------
def extract_episode_number(title):
    """
    Extracts the Season and Episode numbers from a movie/series title for correct sorting.
    Returns (season_num, episode_num). This version is highly robust against bad titles.
    """
    title = title or ""
    title = title.lower()

    # Default values: Season 1, and a very high episode number (for movies or unsorted items)
    season_num = 1
    episode_num = 9999

    # 1. Season extraction (e.g., season 1, s01, s 1)
    season_match = re.search(r"s(?:eason)?\s*(\d+)", title)
    if season_match:
        try:
            season_num = int(season_match.group(1))
        except ValueError:
            pass

    # 2. Episode extraction (e.g., episode 10, e10, e 10)
    episode_match = re.search(r"e(?:pisode)?\s*(\d+)", title)
    if episode_match:
        try:
            episode_num = int(episode_match.group(1))
        except ValueError:
            pass

    # If no explicit episode found, check for a standalone number
    if episode_num == 9999 and season_match:
        cleaned_title = title.replace(season_match.group(0), '')
        simple_number_match = re.search(r"\b(\d+)\b", cleaned_title)
        if simple_number_match:
            try:
                episode_num = int(simple_number_match.group(1))
            except ValueError:
                pass

    return (season_num, episode_num)


# -------------------------------
# Helper function: Extracting order number (e.g., 1., 2., 10.)
# -------------------------------
def extract_movie_order_number(title):
    """
    Extracts the numeric order number (e.g., 1, 2, 10) from the start of a title.
    Returns 9999 if no number is found, ensuring it sorts last.
    """
    title = title or ""
    match = re.match(r'^(\d+)\.', title.strip())
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return 9999


# ----------------------------------------------------------------------
# HOME VIEW (UPDATED: Fixed Pagination issue)
# ----------------------------------------------------------------------
def home(request):
    """Renders the homepage, including search functionality for movies and playlists."""
    query = request.GET.get("q")
    all_playlists = Playlist.objects.all()
    all_movies = Movie.objects.filter(playlist__isnull=True)

    if query:
        playlists_q = Q(name__icontains=query)
        movies_q = Q(title__icontains=query)
        all_playlists = all_playlists.filter(playlists_q)
        all_movies = all_movies.filter(movies_q)

    combined_list = list(chain(all_playlists, all_movies))
    combined_list.sort(
        key=lambda x: x.created_at or timezone.datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )

    # --- Fixed Pagination Logic ---
    page_number = request.GET.get('page')
    
    # Standard pagination: Show 24 items per page.
    # No slicing logic here anymore, so no items will be hidden.
    paginator = Paginator(combined_list, 24)

    try:
        page_obj = paginator.get_page(page_number)
    except EmptyPage:
        page_obj = paginator.get_page(paginator.num_pages)
    except:
        page_obj = paginator.get_page(1)

    not_found = query and not combined_list
    return render(
        request,
        "home.html",
        {
            "media_items": page_obj, # Directly pass page_obj (contains the correct 24 items)
            "categories": Category.objects.all(),
            "query": query,
            "not_found": not_found,
            "page_obj": page_obj,
        },
    )


def playlist_detail(request, playlist_id):
    """
    Displays all movies belonging to a specific playlist.
    """
    playlist = get_object_or_404(Playlist, id=playlist_id)

    movies = list(Movie.objects.filter(playlist=playlist))

    has_numeric_order = False
    for movie in movies[:5]:
        if extract_movie_order_number(movie.title) != 9999:
            has_numeric_order = True
            break

    if has_numeric_order:
        movies.sort(key=lambda movie: extract_movie_order_number(movie.title))
    else:
        movies.sort(key=lambda movie: extract_episode_number(movie.title))

    return render(request, "playlist_detail.html", {"playlist": playlist, "movies": movies})


def category_detail(request, category_id):
    """
    Displays all playlists and movies belonging to a specific category.
    (UPDATED: Fixed Pagination issue)
    """
    category = get_object_or_404(Category, id=category_id)
    query = request.GET.get("q")

    movies = list(Movie.objects.filter(category=category))
    playlists = Playlist.objects.filter(category=category)

    if query:
        movies = [m for m in movies if query.lower() in m.title.lower()]
        playlists = playlists.filter(name__icontains=query)

    # ------------------ SORTING LOGIC ------------------
    has_numeric_order = False
    for movie in movies[:5]:
        if extract_movie_order_number(movie.title) != 9999:
            has_numeric_order = True
            break

    if has_numeric_order:
        movies.sort(key=lambda movie: extract_movie_order_number(movie.title))

    items = [{"type": "movie", "obj": m} for m in movies] + [{"type": "playlist", "obj": p} for p in playlists]

    if not has_numeric_order:
        items.sort(
            key=lambda x: x["obj"].created_at or timezone.datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )

    # --- Fixed Pagination Logic ---
    page_number = request.GET.get('page')

    # Standard pagination: Show 24 items per page.
    paginator = Paginator(items, 24)
    
    try:
        page_obj = paginator.get_page(page_number)
    except EmptyPage:
        page_obj = paginator.get_page(paginator.num_pages)
    except:
        page_obj = paginator.get_page(1)

    return render(request, "category_detail.html", {
        "category": category,
        "items": page_obj, # Directly pass page_obj
        "query": query,
        "page_obj": page_obj,
    })


def movie_detail(request, movie_id):
    """Displays the detail page for a specific movie."""
    movie = get_object_or_404(Movie, id=movie_id)
    return render(request, "movie_detail.html", {"movie": movie})


def get_client_ip(request):
    """Helper function to get the client's IP address."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0]
    return request.META.get("REMOTE_ADDR")


def download_movie(request, movie_id):
    """
    Logs the download event and redirects the user to the actual download link.
    """
    movie = get_object_or_404(Movie, id=movie_id)
    ip = get_client_ip(request)
    agent = request.META.get("HTTP_USER_AGENT", "")
    user_email = request.user.email if request.user.is_authenticated else None
    username = request.user.username if request.user.is_authenticated else None

    DownloadLog.objects.create(
        movie_title=movie.title,
        ip_address=ip,
        user_agent=agent,
        user_email=user_email,
        username=username,
        download_time=timezone.now(),
    )
    return redirect(movie.download_link)


def detect_device_name(user_agent: str) -> str:
    """Tries to detect the device name from the User Agent string."""
    ua = user_agent.lower()
    if "windows" in ua:
        return "Windows PC/Laptop"
    elif "android" in ua:
        return "Android"
    elif "iphone" in ua or "ipad" in ua or "ios" in ua:
        return "iOS"
    elif "mac" in ua:
        return "Mac"
    else:
        return "Unknown"


@csrf_exempt
@require_POST
def track_install(request):
    """API endpoint to track PWA/App installation."""
    try:
        data = json.loads(request.body)
        device_id_str = data.get("device_id")
        device_name = data.get("device_name") or detect_device_name(request.META.get("HTTP_USER_AGENT", ""))

        if not device_id_str:
            return JsonResponse({"status": "error", "message": "Device ID missing"}, status=400)

        tracker, created = InstallTracker.objects.get_or_create(device_id=device_id_str)
        action_message = "Already tracked (count maintained)"

        if created:
            tracker.install_count = 1
            tracker.deleted_count = 0
            tracker.device_info = request.META.get("HTTP_USER_AGENT", "")
            tracker.device_name = device_name
            tracker.last_action = "install"
            action_message = "New install tracked"
        elif tracker.install_count == 0:
            tracker.install_count = 1
            tracker.device_name = device_name
            tracker.last_action = "reinstall"
            action_message = "Re-install tracked (count restored)"
        else:
            tracker.last_action = "install (re-open)"
            tracker.device_name = device_name

        tracker.updated_at = timezone.now()
        tracker.save()
        total_active_installs = InstallTracker.objects.filter(install_count=1).count()

        return JsonResponse({
            "status": "success",
            "message": action_message,
            "device": device_name,
            "total_active_installs": total_active_installs
        })

    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@csrf_exempt
@require_POST
def track_uninstall(request):
    """API endpoint to track PWA/App uninstallation."""
    try:
        data = json.loads(request.body)
        device_id_str = data.get('device_id')

        if not device_id_str:
            return JsonResponse({'success': False, 'message': 'Device ID is required'}, status=400)

        try:
            tracker = InstallTracker.objects.get(device_id=device_id_str)
            if tracker.install_count == 1:
                tracker.install_count = 0
                tracker.deleted_count += 1
                tracker.last_action = 'uninstall'
                tracker.updated_at = timezone.now()
                tracker.save()

            total_active_installs = InstallTracker.objects.filter(install_count=1).count()

            return JsonResponse({'success': True, 'message': 'Uninstall tracked', 'total_active_installs': total_active_installs})
        except InstallTracker.DoesNotExist:
            return JsonResponse({'success': True, 'message': 'Tracker not found, but uninstall acknowledged'})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'Server error'}, status=500)


@staff_member_required
def custom_admin_dashboard(request):
    """Custom admin dashboard view showing key metrics."""
    total_users = User.objects.count()
    total_movies = Movie.objects.count()
    total_downloads = DownloadLog.objects.count()
    total_installs = InstallTracker.objects.filter(install_count=1).count()

    recent_installs = InstallTracker.objects.order_by('-updated_at')[:5]
    top_movies = DownloadLog.objects.values('movie_title').annotate(download_count=Count('movie_title')).order_by('-download_count')[:5]
    recent_downloads = DownloadLog.objects.order_by('-download_time')[:5]

    context = {
        'total_users': total_users,
        'total_movies': total_movies,
        'total_downloads': total_downloads,
        'total_installs': total_installs,
        'recent_installs': recent_installs,
        'top_movies': top_movies,
        'recent_downloads': recent_downloads,
    }
    return render(request, 'admin/index.html', context)


@staff_member_required
def reset_install_data(request):
    """Admin endpoint to clear all install tracking data."""
    InstallTracker.objects.all().delete()
    return JsonResponse({"status": "success", "message": "All install data has been reset."})