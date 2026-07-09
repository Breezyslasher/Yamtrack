from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Comment,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)


class CommentViews(TestCase):
    """Test adding and deleting media comments."""

    def setUp(self):
        """Create a user and a tracked movie to comment on."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.force_login(self.user)

        self.item = Item.objects.create(
            media_id="500",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/m.jpg",
        )
        # bulk_create bypasses Media.save(), which would otherwise fetch
        # metadata from TMDB.
        Movie.objects.bulk_create(
            [Movie(item=self.item, user=self.user, status=Status.COMPLETED.value)],
        )
        self.movie = Movie.objects.get(item=self.item, user=self.user)

    def test_add_comment(self):
        """A comment with text and reaction is created for the user's media."""
        response = self.client.post(
            reverse("add_comment", args=[MediaTypes.MOVIE.value, self.movie.id]),
            {"text": "Great film", "reaction": "love", "is_spoiler": "on"},
        )
        self.assertEqual(response.status_code, 200)

        comment = Comment.objects.get(item=self.item, user=self.user)
        self.assertEqual(comment.text, "Great film")
        self.assertEqual(comment.reaction, "love")
        self.assertTrue(comment.is_spoiler)

    def test_add_comment_requires_text_or_reaction(self):
        """An empty comment is rejected."""
        response = self.client.post(
            reverse("add_comment", args=[MediaTypes.MOVIE.value, self.movie.id]),
            {"text": "", "reaction": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Comment.objects.count(), 0)

    def test_add_reaction_only(self):
        """A reaction with no text is allowed."""
        self.client.post(
            reverse("add_comment", args=[MediaTypes.MOVIE.value, self.movie.id]),
            {"text": "", "reaction": "funny"},
        )
        comment = Comment.objects.get(item=self.item, user=self.user)
        self.assertEqual(comment.reaction, "funny")
        self.assertEqual(comment.text, "")

    def test_invalid_reaction_ignored(self):
        """An unknown reaction value is dropped rather than stored."""
        self.client.post(
            reverse("add_comment", args=[MediaTypes.MOVIE.value, self.movie.id]),
            {"text": "hi", "reaction": "bogus"},
        )
        self.assertEqual(Comment.objects.get().reaction, "")

    def test_delete_comment(self):
        """A user can delete their own comment."""
        comment = Comment.objects.create(
            item=self.item,
            user=self.user,
            text="remove me",
        )
        response = self.client.post(
            reverse(
                "delete_comment",
                args=[MediaTypes.MOVIE.value, self.movie.id, comment.id],
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Comment.objects.filter(id=comment.id).exists())

    def test_cannot_comment_on_another_users_media(self):
        """Commenting on media the user does not own returns 404."""
        other = get_user_model().objects.create_user(
            username="other",
            password="x",  # noqa: S106
        )
        Movie.objects.bulk_create(
            [Movie(item=self.item, user=other, status=Status.COMPLETED.value)],
        )
        other_movie = Movie.objects.get(item=self.item, user=other)
        response = self.client.post(
            reverse("add_comment", args=[MediaTypes.MOVIE.value, other_movie.id]),
            {"text": "sneaky"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Comment.objects.count(), 0)
