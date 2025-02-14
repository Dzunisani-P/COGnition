$(document).ready(function () {
    let currentPage = 1;
    const pageSize = 30;

    // Function to fetch and display data
    function fetchData(page) {
        const formData = new FormData();
        formData.append("taxa_list", $("#taxa_list").val());
        formData.append("remove_redundancy", $("#remove_redundancy").is(":checked"));
        formData.append("page", page);
        formData.append("page_size", pageSize);

        const fileInput = $("#taxa_file")[0];
        if (fileInput.files.length > 0) {
            formData.append("taxa_file", fileInput.files[0]);
        }

        console.log("Fetching data for page:", page);  // Debug

        $.ajax({
            url: "/filter",
            method: "POST",
            data: formData,
            processData: false,  // Required for file uploads
            contentType: false,  // Required for file uploads
            success: function (data) {
                console.log("Received data:", data);  // Debug

                // Update the count
                $("#filtered_count").text(data.count);

                // Update the table with the preview
                $("#proteome_table tbody").empty();
                data.preview.forEach(row => {
                    $("#proteome_table tbody").append(
                        `<tr>
                            <td>${row["Proteome Id"]}</td>
                            <td>${row["Organism"]}</td>
                            <td>${row["Protein count"]}</td>
                        </tr>`
                    );
                });

                // Update the current page
                currentPage = data.page;

                // Enable/disable pagination buttons
                $("#prev_page").toggleClass("disabled", currentPage === 1);
                $("#next_page").toggleClass("disabled", data.preview.length < pageSize);
            },
        });
    }

    // Handle filtering
    $("#filter_form").on("submit", function (e) {
        e.preventDefault();
        currentPage = 1;  // Reset to the first page
        fetchData(currentPage);
    });

    // Handle "Previous" button click
    $("#prev_page").on("click", function (e) {
        e.preventDefault();
        if (currentPage > 1) {
            fetchData(currentPage - 1);
        }
    });

    // Handle "Next" button click
    $("#next_page").on("click", function (e) {
        e.preventDefault();
        fetchData(currentPage + 1);
    });

    // Handle FASTA download
    // Handle FASTA download
    $("#download_fasta").on("click", function (e) {
        e.preventDefault();

        const formData = new FormData();
        formData.append("taxa_list", $("#taxa_list").val());
        formData.append("remove_redundancy", $("#remove_redundancy").is(":checked"));

        const fileInput = $("#taxa_file")[0];
        if (fileInput.files.length > 0) {
            formData.append("taxa_file", fileInput.files[0]);
        }

        $.ajax({
            url: "/download_fasta",
            method: "POST",
            data: formData,
            processData: false,  // Required for file uploads
            contentType: false,  // Required for file uploads
            xhrFields: {
                responseType: 'blob'  // Expect a binary response (FASTA file)
            },
            success: function (data, status, xhr) {
                // Check if the response contains errors
                if (xhr.getResponseHeader("content-type").includes("application/json")) {
                    // Parse the JSON response
                    const reader = new FileReader();
                    reader.onload = function () {
                        const response = JSON.parse(reader.result);
                        if (response.errors) {
                            // Display errors to the user
                            alert("Errors occurred while downloading FASTA files:\n" + response.errors.join("\n"));
                        }
                    };
                    reader.readAsText(data);
                } else {
                    // Create a temporary URL for the downloaded file
                    const url = window.URL.createObjectURL(data);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "proteomes.fasta";  // Set the file name
                    document.body.appendChild(a);
                    a.click();  // Trigger the download
                    window.URL.revokeObjectURL(url);  // Clean up
                }
            },
            error: function (xhr, status, error) {
                console.error("Error downloading FASTA file:", error);
                alert("Failed to download FASTA file, the Uniprot API may be down. Please try again later.");
            }
        });
    });

    // Initial fetch
    fetchData(currentPage);
});