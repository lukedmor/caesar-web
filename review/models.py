from accounts.models import UserProfile
from chunks.models import Chunk
from review import app_settings

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Count

class Comment(models.Model):
    TYPE_CHOICES = (
        ('U', 'User'),
        ('S', 'Static analysis'),
        ('T', 'Test result'),
    )
    text = models.TextField()
    chunk = models.ForeignKey(Chunk, related_name='comments')
    author = models.ForeignKey(User)
    start = models.IntegerField() # region start line, inclusive
    end = models.IntegerField() # region end line, exclusive
    type = models.CharField(max_length=1, choices=TYPE_CHOICES, default='U')
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    parent = models.ForeignKey('self', related_name='child_comments', 
        blank=True, null=True)
    # fields added for denormalization purposes
    upvote_count = models.IntegerField(default=0)
    downvote_count = models.IntegerField(default=0)

    def __unicode__(self):
        return self.text

    #returns child and vote counts for child as a tuple
    def get_child_comment_vote(self):
        return map(self.get_comment_vote, self.child_comments)

    def get_comment_vote(self):
        try:
            vote = self.votes.get(author=request.user.id).value
        except Vote.DoesNotExist:
            vote = None
        return (self, vote)

    def is_reply(self):
        if self.parent:
            return True
        else:
            return False
            
    @staticmethod
    def get_comments_for_chunk(chunk):
        all_comments = []
        parent_comments= \
            Comment.objects.select_related('author') \
                   .filter(chunk=chunk).filter(parent=None)
        for parent_comment in parent_comments:
            temp_stack = [parent_comment]
            while len(temp_stack) != 0:
                temp_child = temp_stack.pop(0)
                all_comments.append(temp_child)
                temp_stack = list(temp_child.child_comments.all()) + temp_stack
        return all_comments

    class Meta:
        ordering = [ 'start', '-end' ]

class Vote(models.Model):
    VALUE_CHOICES = (
        (1, '+1'),
        (-1, '-1'),
    )
    value = models.SmallIntegerField(choices=VALUE_CHOICES)
    comment = models.ForeignKey(Comment, related_name='votes')
    author = models.ForeignKey(User, related_name='votes')

    class Meta:
        unique_together = ('comment', 'author',)

def denormalize_votes(sender, instance, created=False, **kwargs):
    """This recalculates the vote totals for the comment being voted on"""
    comment = instance.comment
    comment.upvote_count = comment.votes.filter(value=1).count()
    comment.downvote_count = comment.votes.filter(value=-1).count()
    comment.save()
models.signals.post_save.connect(denormalize_votes, sender=Vote)
models.signals.post_delete.connect(denormalize_votes, sender=Vote)

class Star(models.Model):
    value = models.BooleanField(default = False)
    chunk = models.ForeignKey(Chunk, related_name = "stars")
    author = models.ForeignKey(User, related_name = "stars")
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

class TaskManager(models.Manager):
    def assign_tasks(self, assignment, user):
        """
        Assigns chunks to the user for review, if the user does not have enough.

        Returns the number of chunks assigned.
        """
        reviewer = user.get_profile()
        current_task_count = Task.objects.filter(reviewer=reviewer, 
                chunk__file__submission__assignment=assignment).count()
        
        assign_count = app_settings.CHUNKS_PER_REVIEWER - current_task_count
        if assign_count <= 0:
            return assign_count
        
        # FIXME this query will probably need to be optimized
        chunks = Chunk.objects.exclude(file__submission__name=user.username) \
            .filter(file__submission__assignment=assignment) \
            .exclude(tasks__reviewer=reviewer) \
            .annotate(reviewer_count=Count('tasks')) \
            .filter(reviewer_count__lt=app_settings.REVIEWERS_PER_CHUNK) \
            .order_by('-reviewer_count')[0:assign_count]
        for chunk in chunks:
            task = Task(reviewer=user.get_profile(), chunk=chunk)
            task.save()
            
        return assign_count

class Task(models.Model):
    STATUS_CHOICES=(
        ('N', 'New'),
        ('S', 'Started'),
        ('C', 'Complete'),
    )
    chunk = models.ForeignKey(Chunk, related_name='tasks')
    reviewer = models.ForeignKey(UserProfile, related_name='tasks')
    due = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=1, choices=STATUS_CHOICES, default='N')
    created = models.DateTimeField(auto_now_add=True)
    objects = TaskManager()
    class Meta:
        unique_together = ('chunk', 'reviewer',)
    
    def __unicode__(self):
        return "Task: %s - %s" % (self.reviewer.user, self.chunk)
