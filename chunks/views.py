from chunks.models import Chunk, File, Assignment, Submission, StaffMarker
from review.models import Comment, Vote, Star 
from tasks.models import Task

from django.http import Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.template import RequestContext
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from pygments import highlight
from pygments.lexers import JavaLexer
from pygments.formatters import HtmlFormatter

import os
import subprocess
import datetime
import sys

@login_required
def view_chunk(request, chunk_id):
    user = request.user
    chunk = get_object_or_404(Chunk, pk=chunk_id)
    if user.profile.is_student() and not chunk.file.submission.assignment.is_current_semester() and user != chunk.file.submission.author:
        raise Http404
    user_votes = dict((vote.comment_id, vote.value) \
            for vote in user.votes.filter(comment__chunk=chunk_id))

    staff_lines = StaffMarker.objects.filter(chunk=chunk).order_by('start_line', 'end_line')

    def get_comment_data(comment):
        vote = user_votes.get(comment.id, None)
        snippet = chunk.generate_snippet(comment.start, comment.end)
        return (comment, vote, snippet)

    comment_data = map(get_comment_data, 
                       chunk.comments.select_related('author__profile'))

    lexer = JavaLexer()
    formatter = HtmlFormatter(cssclass='syntax', nowrap=True)
    numbers, lines = zip(*chunk.lines)
    # highlight the code this way to correctly identify multi-line constructs
    # TODO implement a custom formatter to do this instead
    highlighted = zip(numbers, 
            highlight(chunk.data, lexer, formatter).splitlines())
    highlighted_lines = []
    staff_line_index = 0
    for number, line in highlighted:
        if staff_line_index < len(staff_lines) and number >= staff_lines[staff_line_index].start_line and number <= staff_lines[staff_line_index].end_line:
            while staff_line_index < len(staff_lines) and number == staff_lines[staff_line_index].end_line:
                staff_line_index += 1
            highlighted_lines.append((number, line, True))
        else:
            highlighted_lines.append((number, line, False)) 
    
    task_count = Task.objects.filter(reviewer=user.get_profile()) \
            .exclude(status='C').exclude(status='U').count()
    # get the associated task if it exists
    try:
        task = Task.objects.get(chunk=chunk, reviewer=user.get_profile())
        if task.status == 'N':
            task.mark_as('O')
    except Task.DoesNotExist:
        task = None
    return render(request, 'chunks/view_chunk.html', { 
        'chunk': chunk,
        'similar_chunks': chunk.get_similar_chunks(),
        'highlighted_lines': highlighted_lines,
        'comment_data': comment_data,
        'task': task,
        'task_count': task_count,
        'full_view': True,
        'file': chunk.file
    }) 

@login_required
def view_all_chunks(request, viewtype, submission_id):
    user = request.user
    files = File.objects.filter(submission=submission_id).select_related('chunks')
    submission = Submission.objects.get(id = submission_id)
    if not files:
        raise Http404
    assignment = files[0].submission.assignment
    assignment_name = assignment.name
    if user.profile.is_student() and not assignment.is_current_semester() and user != submission.author:
        raise Http404
    paths = []
    user_stats = []
    static_stats = []
    all_highlighted_lines = []
    for afile in files:
        paths.append(afile.path)
    common_prefix = ""
    if len(paths) > 1:
        common_prefix = os.path.commonprefix(paths)
    
    #get a list of only the relative paths
    paths = []
    for afile in files:
        paths.append(os.path.relpath(afile.path, common_prefix))

    lexer = JavaLexer()
    formatter = HtmlFormatter(cssclass='syntax', nowrap=True)
    for afile in files:
        staff_lines = StaffMarker.objects.filter(chunk__file=afile).order_by('start_line', 'end_line')
        
        #prepare the file - get the lines that are part of chunk and the ones that aren't
        highlighted_lines_for_file = []
        numbers, lines = zip(*afile.lines)
        highlighted = zip(numbers, 
                highlight(afile.data, lexer, formatter).splitlines())
                
        highlighted_lines = []
        staff_line_index = 0
        for number, line in highlighted:
            if staff_line_index < len(staff_lines) and number >= staff_lines[staff_line_index].start_line and number <= staff_lines[staff_line_index].end_line:
                while staff_line_index < len(staff_lines) and number == staff_lines[staff_line_index].end_line:
                    staff_line_index += 1
                highlighted_lines.append((number, line, True))
            else:
                highlighted_lines.append((number, line, False))        
        
        chunks = afile.chunks.order_by('start')
        total_lines = len(afile.lines)
        offset = numbers[0]
        start = offset
        end = offset
        user_comments = 0
        static_comments = 0
        for chunk in chunks:
            numbers, lines = zip(*chunk.lines)
            chunk_start = numbers[0]
            chunk_end = chunk_start + len(numbers)
            if end != chunk_start and chunk_start > end: #some lines between chunks
                #non chunk part
                start = end
                end = chunk_start
                #True means it's a chunk, False it's not a chunk
                highlighted_lines_for_file.append((highlighted_lines[start-offset:end - offset], False, None, None))
            if end == chunk_start:
                #get comments and count them
                def get_comment_data(comment):
                    snippet = chunk.generate_snippet(comment.start, comment.end)
                    return (comment, snippet)
                
                comments = chunk.comments.select_related('chunk', 'author__profile')
                comment_data = map(get_comment_data, comments)
                
                user_comments += comments.filter(type='U').count()
                static_comments += comments.filter(type='S').count()
                
                #now for the chunk part
                start = chunk_start
                end = chunk_end
                #True means it's a chunk, False it's not a chunk
                highlighted_lines_for_file.append((highlighted_lines[start-offset:end-offset], True, chunk, comment_data))
        #see if there is anything else to grab 
        highlighted_lines_for_file.append((highlighted_lines[end-offset:], False, None, None))
        user_stats.append(user_comments)
        static_stats.append(static_comments)
        all_highlighted_lines.append(highlighted_lines_for_file)
    file_data = zip(paths, all_highlighted_lines, files)
    
    code_only = False
    comment_view = True
    if viewtype == "code":
        code_only = True
        comment_view = False
    
    path_and_stats = zip(paths, user_stats, static_stats)
    
    return render(request, 'chunks/view_all_chunks.html', {
        'assignment_name': assignment_name,
        'path_and_stats': path_and_stats,
        'file_data': file_data,
        'code_only': code_only,
        'read_only': False,
        'comment_view': comment_view,
        'full_view': True,
    })
@login_required
def submit_assignment(request, assignment_id):
    user = request.user
    current_assignment = Assignment.objects.get(id=assignment_id)
    if datetime.datetime.now() > current_assignment.duedate:
        return render(request, 'chunks/submit_assignment.html', {
            'submission': submission,
            'author': author,
            'new_submission': False,
            'late': True
        })
    #check if there is an existing submission 
    submission = Submission.objects.get(author=user, assignment=current_assignment)
    p = subprocess.Popen(['/Users/elena/Documents/Praetor/praetor/codeTester', '/Users/elena/Documents/Praetor/server_files/trunk'], stdout=subprocess.PIPE)
    afile, err = p.communicate()
    changedate = "Last Changed Date: "
    changerevision = "Last Changed Rev: "
    changeauthor = "Last Changed Author: "
    dateindex = afile.find(changedate)
    date = afile[dateindex + len(changedate):]
    year, month, day = date.split(" ")[0].split("-")
    hour, minute, sec = date.split(" ")[1].split(":")
    submission.revision_date = datetime.datetime(int(year), int(month), int(day), int(hour), int(minute), int(sec))
    #warn about time since last submission
    hour_buffer = datetime.datetime.now() - datetime.timedelta(hours=1)
    warn_hours = False
    if submission.revision_date < hour_buffer:
        warn_hours = True
    revindex = afile.find(changerevision)
    rev = int(afile[revindex + len(changerevision): dateindex])
    #check that this is a new revision and not the one that was already stored
    new_submission = True
    if rev == submission.revision:
        new_submission = False
    submission.revision = rev
    #verify author
    authorindex = afile.find(changeauthor)
    author = afile[authorindex + len(changeauthor): revindex]
    submission.save()
    return redirect('review.views.dashboard')
@login_required
def simualte(request, assignment_id):
    user = request.user
    assignment = Assignment.objects.get(id=assignment_id)
    assignment_chunks = Chunk.objects.filter(file__submission__assignment__id = assignment_id).select_related('file__submission__assignment', 'profile')
    
    chunks_graph = dict()
    important = set()
    test = set()
    for chunk in assignment_chunks:
        name = chunk.name
        lines_dict = dict()
        if name in chunks_graph:
            lines_dict = chunks_graph[name]
        lines = min(chunk.profile.student_lines, 200)
        if lines in lines_dict:
            lines_dict[lines] += 1
        else:
            lines_dict[lines] = 1
        if lines > 30:
            important.add(name)
            if chunk.class_type == "TEST":
                test.add(name)
        chunks_graph[name] = lines_dict
    
    #list of lists ["sudoku", [[1,20], [3,50]]]
    #list of important and unimportant 
    important_graphs = []
    test_graphs = []
    unimportant_graphs = []
    for name in chunks_graph.keys():
        lines_dict = chunks_graph[name]
        lines_list = []
        for key in lines_dict.keys():
            lines_list.append([int(key), lines_dict[key]])
        if name in test:
            test_graphs.append([name, lines_list])
        elif name in important:
            important_graphs.append([name, lines_list])
        else:
            unimportant_graphs.append([name, lines_list])
    
    
    if request.method == 'GET':
        students = assignment.students
        alums = assignment.alums
        staff = assignment.staff
    
        #find all active students, students that have at least pulled the assignment
        all_students = User.objects.filter(submissions__assignment = assignment)
        active_students = []
        for student in all_students:
            chunks = Chunk.objects.filter(file__submission__assignment = assignment).filter(file__submission__author=student)
            if chunks.count() > 0:
                active_students.append(student)
        
        chunks_data = []
        to_assign = assignment.chunks_to_assign

        #find all classes that are worth reviewing, not tests and code more than 40 lines
        classes = assignment_chunks.filter(class_type = "NONE").filter(profile__student_lines__gt = 30).exclude(name="Main")

        dist = dict()
        for chunk in classes:
            name = chunk.name
            if name in dist:
                dist[name] += 1
            else:
                dist[name] = 1

        for w in sorted(dist, key=dist.get, reverse=True):
            to_assign += w + " " + str(dist[w]) + " 1 1,"
            chunks_data.append((w, dist[w], 1))

        
        assignment.chunks_to_assign = to_assign
        assignment.save()
            # chunks_info = to_assign.split(",")
            # for chunk_info in chunks_info:
            #     info = chunk_info.split(" ")
            #     if len(info) == 4:
            #         if int(info[2]):
            #             chunks_data.append((info[0], info[1], int(info[3])))

        
        return render(request, 'chunks/simulate.html', {
            'assignment': assignment,
            'chunks_data': chunks_data,
            'important_graph': important_graphs,
            'unimportant_graph': unimportant_graphs,
            'test_graph': test_graphs,
        })
    else:
        students = request.POST['students']
        alums = request.POST['alums']
        staff = request.POST['staff']
        assignment.students = students
        assignment.alums = alums
        assignment.staff = staff
        
        assignment.student_count = request.POST['student_tasks']
        assignment.alum_count = request.POST['alum_tasks']
        assignment.staff_count = request.POST['staff_tasks']
        assignment.save()
        #find all active students, students that have at least pulled the assignment
        all_students = User.objects.filter(submissions__assignment = assignment)
        active_students = []
        for student in all_students:
            chunks = Chunk.objects.filter(file__submission__assignment = assignment).filter(file__submission__author=student)
            if chunks.count() > 0:
                active_students.append(student)
        
        #find all classes that are worth reviewing, not tests and code more than 30 lines
        classes = assignment_chunks.filter(class_type = "NONE").filter(profile__student_lines__gt = 30).exclude(name="Main")
        
        chunks_data = []
        test_data = []
        to_assign = assignment.chunks_to_assign
        chunks_info = to_assign.split(",")
        for chunk_info in chunks_info:
            info = chunk_info.split(" ")
            if len(info) == 4:
                if int(info[2]):
                    chunks_data.append((info[0], info[1], int(info[3])))
                else:
                    test_data.append((info[0], info[1], int(info[3])))
        
        chunks_raw = request.POST.getlist('chunk')
        checked = set()
        for raw in chunks_raw:
            chunk_name = raw.split("-")[0]
            checked.add(chunk_name)
        
        to_assign = ""
        for name, num, old in chunks_data:
            if name in checked:
                to_assign += name + " " + str(num) + " 1 1,"
            else:
                to_assign += name + " " + str(num) + " 1 0,"
           
        
        assignment.chunks_to_assign = to_assign
        assignment.save()
        
        chunks_data = []
        test_data = []
        chunks_info = to_assign.split(",")
        for chunk_info in chunks_info:
            info = chunk_info.split(" ")
            if len(info) == 4:
                if int(info[2]):
                    chunks_data.append((info[0], info[1], int(info[3])))
                else:
                    test_data.append((info[0], info[1], int(info[3])))
        
        return render(request, 'chunks/simulate.html', {
            'assignment': assignment,
            'chunks_data': chunks_data,
        })
    