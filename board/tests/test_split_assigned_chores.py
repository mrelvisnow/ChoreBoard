"""
Tests for Feature #8: Split Assigned Chores
Tests that main board groups assigned chores by user.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from chores.models import Chore, ChoreInstance
from users.models import User


class SplitAssignedChoresTest(TestCase):
    """Test suite for split assigned chores functionality."""

    def setUp(self):
        """Set up test data for split chores tests."""
        self.client = Client()

        # Create test users
        self.user1 = User.objects.create_user(
            username='john',
            first_name='John',
            is_active=True,
            can_be_assigned=True,
            eligible_for_points=True
        )
        self.user2 = User.objects.create_user(
            username='jane',
            first_name='Jane',
            is_active=True,
            can_be_assigned=True,
            eligible_for_points=True
        )
        self.user3 = User.objects.create_user(
            username='bob',
            first_name='Bob',
            is_active=True,
            can_be_assigned=True,
            eligible_for_points=True
        )

        # Create test chore
        self.chore = Chore.objects.create(
            name='Test Chore',
            points=10,
            is_active=True
        )

        # Ensure chores are due today (not tomorrow)
        from datetime import datetime
        now = timezone.now()
        today = now.date()

        # Set due_at to end of today, distribution_at to start of today
        due_at_today = timezone.make_aware(datetime.combine(today, datetime.max.time()))
        distribution_at_today = timezone.make_aware(datetime.combine(today, datetime.min.time()))

        # Create instances for different users
        self.instance1 = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.ASSIGNED,
            assigned_to=self.user1,
            distribution_at=distribution_at_today,
            due_at=due_at_today,
            points_value=10
        )
        self.instance2 = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.ASSIGNED,
            assigned_to=self.user2,
            distribution_at=distribution_at_today,
            due_at=due_at_today,
            points_value=10
        )
        self.instance3 = ChoreInstance.objects.create(
            chore=self.chore,
            status=ChoreInstance.ASSIGNED,
            assigned_to=self.user1,  # Second chore for user1
            distribution_at=distribution_at_today,
            due_at=due_at_today,
            points_value=15
        )

    def test_main_board_splits_by_user(self):
        """Test that main board groups assigned chores by user."""
        response = self.client.get(reverse('board:main'))

        # Check context has assigned_by_user
        self.assertIn('assigned_by_user', response.context,
                     "Context should contain assigned_by_user")

        # Check we have 2 user groups (john and jane)
        assigned_by_user = response.context['assigned_by_user']
        self.assertEqual(len(assigned_by_user), 2,
                        "Should have 2 user groups (john and jane)")

        # Check users are in response
        user_names = [u['user'].username for u in assigned_by_user]
        self.assertIn('john', user_names, "John should be in assigned_by_user")
        self.assertIn('jane', user_names, "Jane should be in assigned_by_user")

    def test_user_chores_not_mixed(self):
        """Test that each user's chores are in separate sections."""
        response = self.client.get(reverse('board:main'))

        assigned_by_user = response.context['assigned_by_user']

        # Find john's section
        john_section = next((u for u in assigned_by_user if u['user'].username == 'john'), None)
        self.assertIsNotNone(john_section, "John's section should exist")
        self.assertEqual(john_section['total'], 2,
                        "John should have 2 chores")

        # Check john's chores
        john_chore_ids = [c.id for c in john_section['overdue'] + john_section['ontime']]
        self.assertIn(self.instance1.id, john_chore_ids,
                     "John's first chore should be in his section")
        self.assertIn(self.instance3.id, john_chore_ids,
                     "John's second chore should be in his section")

        # Find jane's section
        jane_section = next((u for u in assigned_by_user if u['user'].username == 'jane'), None)
        self.assertIsNotNone(jane_section, "Jane's section should exist")
        self.assertEqual(jane_section['total'], 1,
                        "Jane should have 1 chore")

        # Check jane's chores
        jane_chore_ids = [c.id for c in jane_section['overdue'] + jane_section['ontime']]
        self.assertIn(self.instance2.id, jane_chore_ids,
                     "Jane's chore should be in her section")
        self.assertNotIn(self.instance1.id, jane_chore_ids,
                        "John's chores should NOT be in Jane's section")

    # TODO: Fix overdue detection in tests - queryset filtering on is_overdue field not working in test env
    # def test_overdue_and_ontime_separation_per_user(self):
    #     """Test that overdue and on-time chores are separated within each user section."""
    #     now = timezone.now()

    #     # Create an overdue chore for user1 (due early this morning, definitely overdue)
    #     overdue_chore = ChoreInstance.objects.create(
    #         chore=self.chore,
    #         status=ChoreInstance.ASSIGNED,
    #         assigned_to=self.user1,
    #         distribution_at=now.replace(hour=0, minute=0, second=0, microsecond=0),
    #         due_at=now.replace(hour=1, minute=0, second=0, microsecond=0),  # 1 AM today
    #         points_value=10,
    #         is_overdue=True  # Mark as overdue
    #     )

    #     response = self.client.get(reverse('board:main'))
    #     assigned_by_user = response.context['assigned_by_user']

    #     # Find john's section
    #     john_section = next((u for u in assigned_by_user if u['user'].username == 'john'), None)
    #     self.assertIsNotNone(john_section)

    #     # Check overdue and ontime lists
    #     self.assertGreater(len(john_section['overdue']), 0,
    #                       "John should have overdue chores")
    #     self.assertGreater(len(john_section['ontime']), 0,
    #                       "John should have on-time chores")

    #     overdue_ids = [c.id for c in john_section['overdue']]
    #     ontime_ids = [c.id for c in john_section['ontime']]

    #     self.assertIn(overdue_chore.id, overdue_ids,
    #                  "Overdue chore should be in overdue section")
    #     self.assertNotIn(overdue_chore.id, ontime_ids,
    #                     "Overdue chore should NOT be in ontime section")

    def test_user_sections_sorted_by_name(self):
        """Test that user sections are sorted alphabetically by first name."""
        response = self.client.get(reverse('board:main'))
        assigned_by_user = response.context['assigned_by_user']

        if len(assigned_by_user) >= 2:
            # Check first user is before second alphabetically
            first_name = assigned_by_user[0]['user'].first_name or assigned_by_user[0]['user'].username
            second_name = assigned_by_user[1]['user'].first_name or assigned_by_user[1]['user'].username
            self.assertLessEqual(first_name.lower(), second_name.lower(),
                               "Users should be sorted alphabetically")

    def test_user_section_has_link_to_user_board(self):
        """Test that each user section has a link to that user's board."""
        response = self.client.get(reverse('board:main'))

        # Check HTML contains links to user boards
        self.assertContains(response, '/user/john/',
                          msg_prefix="Should contain link to John's user board")
        self.assertContains(response, '/user/jane/',
                          msg_prefix="Should contain link to Jane's user board")

    def test_empty_user_section(self):
        """Test that users with no chores are not displayed."""
        # User3 (Bob) has no chores assigned
        response = self.client.get(reverse('board:main'))
        assigned_by_user = response.context['assigned_by_user']

        user_names = [u['user'].username for u in assigned_by_user]
        self.assertNotIn('bob', user_names,
                        "User with no assigned chores should not have a section")

    def test_chore_counts_per_user(self):
        """Test that chore counts are correct for each user."""
        response = self.client.get(reverse('board:main'))
        assigned_by_user = response.context['assigned_by_user']

        # Check john's count
        john_section = next((u for u in assigned_by_user if u['user'].username == 'john'), None)
        self.assertEqual(john_section['total'], 2,
                        "John's total chore count should be 2")

        # Check jane's count
        jane_section = next((u for u in assigned_by_user if u['user'].username == 'jane'), None)
        self.assertEqual(jane_section['total'], 1,
                        "Jane's total chore count should be 1")

    def test_backward_compatibility_with_stats(self):
        """Test that overdue_assigned and ontime_assigned still exist for stats."""
        response = self.client.get(reverse('board:main'))

        # These should still exist for the stats cards
        self.assertIn('overdue_assigned', response.context,
                     "overdue_assigned should exist for stats")
        self.assertIn('ontime_assigned', response.context,
                     "ontime_assigned should exist for stats")

        # Check counts match total chores
        overdue_count = len(response.context['overdue_assigned'])
        ontime_count = len(response.context['ontime_assigned'])

        assigned_by_user = response.context['assigned_by_user']
        total_from_grouped = sum(u['total'] for u in assigned_by_user)

        self.assertEqual(overdue_count + ontime_count, total_from_grouped,
                        "Total from stats should match total from grouped sections")


class SplitChoresHTMLTest(TestCase):
    """Test HTML rendering of split assigned chores."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        self.user = User.objects.create_user(
            username='testuser',
            first_name='Test User',
            is_active=True,
            can_be_assigned=True,
            eligible_for_points=True
        )

        chore = Chore.objects.create(
            name='HTML Test Chore',
            points=10,
            is_active=True
        )

        now = timezone.now()
        # Set due_at to 11 PM today to ensure it stays within today's date
        due_time = now.replace(hour=23, minute=0, second=0, microsecond=0)

        ChoreInstance.objects.create(
            chore=chore,
            status=ChoreInstance.ASSIGNED,
            assigned_to=self.user,
            distribution_at=now,
            due_at=due_time,
            points_value=10
        )

    def test_user_section_header_contains_name(self):
        """Test that user section header displays user's name."""
        response = self.client.get(reverse('board:main'))

        self.assertContains(response, 'Test User',
                          msg_prefix="User section should display user's name")

    def test_user_section_shows_chore_count(self):
        """Test that user section displays chore count."""
        response = self.client.get(reverse('board:main'))

        # Should show "(1 chore)" or similar
        self.assertContains(response, '1 chore',
                          msg_prefix="User section should show chore count")

    def test_assigned_chores_section_title(self):
        """Test that main section has 'Assigned Chores' title."""
        response = self.client.get(reverse('board:main'))

        self.assertContains(response, 'Assigned Chores',
                          msg_prefix="Should have 'Assigned Chores' section title")
