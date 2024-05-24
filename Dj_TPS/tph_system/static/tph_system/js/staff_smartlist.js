$('#myList a[href="#home"]').on('click', function (e) {
    e.preventDefault()
    $(this).tab('show')
})
$('#myList a[href="#profile"]').on('click', function (e) {
    e.preventDefault()
    $(this).tab('show')
})
$('#myList a[href="#messages"]').on('click', function (e) {
    e.preventDefault()
    $(this).tab('show')
})
$('#myList a[href="#settings"]').on('click', function (e) {
    e.preventDefault()
    $(this).tab('show')
})
$(function () {
    $('#myList a[href="#home"]').tab('show')
    $('#myList a[href="#profile"]').tab('show')
    $('#myList a[href="#messages"]').tab('show')
    $('#myList a[href="#settings"]').tab('show')
})